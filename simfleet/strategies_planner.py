import json

from loguru import logger
from spade.behaviour import State, FSMBehaviour

from simfleet.customer import CustomerStrategyBehaviour
from simfleet.fleetmanager import FleetManagerStrategyBehaviour
from simfleet.helpers import PathRequestException, distance_in_meters
from simfleet.protocol import REQUEST_PERFORMATIVE, ACCEPT_PERFORMATIVE, REFUSE_PERFORMATIVE, REQUEST_PROTOCOL, \
    INFORM_PERFORMATIVE, CANCEL_PERFORMATIVE, PROPOSE_PERFORMATIVE, QUERY_PROTOCOL
from simfleet.transport import TransportStrategyBehaviour
from simfleet.utils import TRANSPORT_WAITING, TRANSPORT_WAITING_FOR_APPROVAL, TRANSPORT_MOVING_TO_CUSTOMER, \
    TRANSPORT_NEEDS_CHARGING, TRANSPORT_MOVING_TO_STATION, TRANSPORT_IN_STATION_PLACE, TRANSPORT_CHARGING, \
    TRANSPORT_CHARGED, CUSTOMER_WAITING, CUSTOMER_ASSIGNED, TRANSPORT_RELOCATING


################################################################
#                                                              #
#                     FleetManager Strategy                    #
#                                                              #
################################################################
class DelegateRequestBehaviour(FleetManagerStrategyBehaviour):
    """
    The default strategy for the FleetManager agent. By default it delegates all requests to all transports.
    """

    async def run(self):
        if not self.agent.registration:
            await self.send_registration()

        msg = await self.receive(timeout=5)
        logger.debug("Manager received message: {}".format(msg))
        if msg:
            for transport in self.get_transport_agents().values():
                msg.to = str(transport["jid"])
                logger.debug("Manager sent request to transport {}".format(transport["name"]))
                await self.send(msg)


################################################################
#                                                              #
#                     Transport Strategy                       #
#                                                              #
################################################################
class TransportGetActionState(TransportStrategyBehaviour, State):

    async def on_start(self):
        await super().on_start()
        self.agent.status = TRANSPORT_WAITING
        logger.debug("{} in Transport Waiting State".format(self.agent.jid))

    async def run(self):
        # Get next action from queue
        action = self.agent.get_next_action()
        # Check action type
        action_type = action.get('type')
        attributes = action.get('attributes')
        # If it is a charging action, extract station and position, start movement
        if action_type == 'CHARGE':
            station = attributes.get('station_id')
            station_position = attributes.get('station_position')
            self.agent.current_station_dest = (station, station_position)
            logger.info("Transport {} selected station {}.".format(self.agent.name, station))
            try:
                station, position = self.agent.current_station_dest
                await self.go_to_the_station(station, position)
                self.set_next_state(TRANSPORT_MOVING_TO_STATION)
                return
            except PathRequestException:
                logger.error("Transport {} could not get a path to station {}. Cancelling..."
                             .format(self.agent.name, station))
                await self.cancel_proposal(station)
                # self.set_next_state(TRANSPORT_WAITING)
                return
            except Exception as e:
                logger.error("Unexpected error in transport {}: {}".format(self.agent.name, e))
                # self.set_next_state(TRANSPORT_WAITING)
                return
        # If it is a customer pick-up action, extract customer position, start movement
        elif action_type == 'CUSTOMER':
            customer_id = attributes.get('customer_id')
            customer_origin = attributes.get('customer_origin')
            customer_dest = attributes.get('customer_dest')
            try:
                # new version
                self.agent.status = TRANSPORT_MOVING_TO_CUSTOMER
                await self.pick_up_customer(customer_id, customer_origin, customer_dest)
                self.set_next_state(TRANSPORT_MOVING_TO_CUSTOMER)
                return
            except PathRequestException:
                logger.error("Transport {} could not get a path to customer {}. Cancelling..."
                             .format(self.agent.name,customer_id))
                await self.cancel_proposal(customer_id)
                # self.set_next_state(TRANSPORT_WAITING)
                return
            except Exception as e:
                logger.error("Unexpected error in transport {}: {}".format(self.agent.name, e))
                await self.cancel_proposal(customer_id)
                # self.set_next_state(TRANSPORT_WAITING)
                return
        # If it is a relocation, extract new position, start movement
        elif action_type == 'RELOCATE':
            new_position = attributes.get('new_position')
            try:
                await self.agent.move_to(new_position)
                self.set_next_state(TRANSPORT_RELOCATING)
            except PathRequestException:
                logger.error("Transport {} could not get a path to new position {}. Cancelling..."
                             .format(self.agent.name, new_position))
                return
            except Exception as e:
                logger.error("Unexpected error in transport {}: {}".format(self.agent.name, e))
                # self.set_next_state(TRANSPORT_WAITING)
                return



class TransportMovingToStationState(TransportStrategyBehaviour, State):

    async def on_start(self):
        await super().on_start()
        self.agent.status = TRANSPORT_MOVING_TO_STATION
        logger.debug("{} in Transport Moving to Station".format(self.agent.jid))

    async def run(self):
        if self.agent.get("in_station_place"):
            logger.warning("Transport {} already in station place".format(self.agent.jid))
            await self.agent.request_access_station()
            return self.set_next_state(TRANSPORT_IN_STATION_PLACE)
        self.agent.transport_in_station_place_event.clear()  # new
        self.agent.watch_value("in_station_place", self.agent.transport_in_station_place_callback)
        await self.agent.transport_in_station_place_event.wait()
        await self.agent.request_access_station()  # new
        return self.set_next_state(TRANSPORT_IN_STATION_PLACE)


class TransportInStationState(TransportStrategyBehaviour, State):
    # car arrives to the station and waits in queue until receiving confirmation
    async def on_start(self):
        await super().on_start()
        logger.debug("{} in Transport In Station Place State".format(self.agent.jid))
        self.agent.status = TRANSPORT_IN_STATION_PLACE

    async def run(self):
        # await self.agent.request_access_station()
        # self.agent.status = TRANSPORT_IN_STATION_PLACE
        msg = await self.receive(timeout=60)
        if not msg:
            self.set_next_state(TRANSPORT_IN_STATION_PLACE)
            return
        content = json.loads(msg.body)
        performative = msg.get_metadata("performative")
        if performative == ACCEPT_PERFORMATIVE:
            if content.get('station_id') is not None:
                # debug
                logger.debug("Transport {} received a message with ACCEPT_PERFORMATIVE from {}".format(self.agent.name,
                                                                                                       content[
                                                                                                           "station_id"]))
                await self.charge_allowed()
                self.set_next_state(TRANSPORT_CHARGING)
                return

        else:
            # if the message I receive is not an ACCEPT, I keep waiting in the queue
            self.set_next_state(TRANSPORT_IN_STATION_PLACE)
            return


class TransportChargingState(TransportStrategyBehaviour, State):
    # car charges in a station
    async def on_start(self):
        await super().on_start()
        # self.agent.status = TRANSPORT_CHARGING # this change is already performed in function begin_charging() of class Transport
        logger.debug("{} in Transport Charging State".format(self.agent.jid))

    async def run(self):
        # await "transport_charged" message
        msg = await self.receive(timeout=60)
        if not msg:
            self.set_next_state(TRANSPORT_CHARGING)
            return
        content = json.loads(msg.body)
        protocol = msg.get_metadata("protocol")
        performative = msg.get_metadata("performative")
        if protocol == REQUEST_PROTOCOL and performative == INFORM_PERFORMATIVE:
            if content["status"] == TRANSPORT_CHARGED:
                self.agent.transport_charged()
                await self.agent.drop_station()
                # canviar per un event?
                self.set_next_state(TRANSPORT_WAITING)
                return
        else:
            self.set_next_state(TRANSPORT_CHARGING)
            return


class TransportMovingToCustomerState(TransportStrategyBehaviour, State):

    async def on_start(self):
        await super().on_start()
        self.agent.status = TRANSPORT_MOVING_TO_CUSTOMER
        logger.debug("{} in Transport Moving To Customer State".format(self.agent.jid))

    async def run(self):
        # Reset internal flag to False. coroutines calling
        # wait() will block until set() is called
        self.agent.customer_in_transport_event.clear()
        # Registers an observer callback to be run when the "customer_in_transport" is changed
        self.agent.watch_value("customer_in_transport", self.agent.customer_in_transport_callback)
        # block behaviour until another coroutine calls set()
        await self.agent.customer_in_transport_event.wait()
        # no s'está accedint a aquesta part del codi
        return self.set_next_state(TRANSPORT_WAITING)

class TransportRelocatingState(TransportStrategyBehaviour, State):

    async def on_start(self):
        await super().on_start()
        self.agent.status = TRANSPORT_RELOCATING
        logger.debug("{} in Transport Relocating State".format(self.agent.jid))

    async def run(self):
        self.agent.transport_relocated_event.clear()
        self.agent.watch_value("transport_relocated", self.agent.transport_relocated_callback)
        await self.agent.transport_relocated_event.wait()
        return self.set_next_state(TRANSPORT_WAITING)


class FSMTransportStrategyBehaviour(FSMBehaviour):
    def setup(self):
        # Create states
        self.add_state(TRANSPORT_WAITING, TransportGetActionState(), initial=True)
        # self.add_state(TRANSPORT_NEEDS_CHARGING, TransportNeedsChargingState())
        # self.add_state(TRANSPORT_WAITING_FOR_APPROVAL, TransportWaitingForApprovalState())

        self.add_state(TRANSPORT_MOVING_TO_CUSTOMER, TransportMovingToCustomerState())
        # self.add_state(TRANSPORT_MOVING_TO_CUSTOMER, MyTransportMovingToCustomerState())

        self.add_state(TRANSPORT_MOVING_TO_STATION, TransportMovingToStationState())
        self.add_state(TRANSPORT_IN_STATION_PLACE, TransportInStationState())
        self.add_state(TRANSPORT_CHARGING, TransportChargingState())

        self.add_state(TRANSPORT_RELOCATING, TransportRelocatingState())

        # Create transitions
        self.add_transition(TRANSPORT_WAITING, TRANSPORT_MOVING_TO_STATION) # do charging action
        self.add_transition(TRANSPORT_WAITING, TRANSPORT_MOVING_TO_CUSTOMER) # do customer action



        self.add_transition(TRANSPORT_MOVING_TO_STATION, TRANSPORT_IN_STATION_PLACE)  # arrived to station
        self.add_transition(TRANSPORT_IN_STATION_PLACE, TRANSPORT_IN_STATION_PLACE)  # waiting in station queue
        self.add_transition(TRANSPORT_IN_STATION_PLACE, TRANSPORT_CHARGING)  # begin charging
        self.add_transition(TRANSPORT_CHARGING, TRANSPORT_CHARGING)  # waiting to finish charging
        self.add_transition(TRANSPORT_CHARGING, TRANSPORT_WAITING)  # restart strategy

        self.add_transition(TRANSPORT_MOVING_TO_CUSTOMER, TRANSPORT_MOVING_TO_CUSTOMER)
        self.add_transition(TRANSPORT_MOVING_TO_CUSTOMER,
                            TRANSPORT_WAITING)  # picked up customer or arrived to destination ??


################################################################
#                                                              #
#                       Customer Strategy                      #
#                                                              #
################################################################
class AcceptFirstRequestBehaviour(CustomerStrategyBehaviour):
    """
    The default strategy for the Customer agent. By default it accepts the first proposal it receives.
    """

    async def run(self):
        if self.agent.fleetmanagers is None:
            await self.send_get_managers(self.agent.fleet_type)

            msg = await self.receive(timeout=5)
            if msg:
                protocol = msg.get_metadata("protocol")
                if protocol == QUERY_PROTOCOL:
                    performative = msg.get_metadata("performative")
                    if performative == INFORM_PERFORMATIVE:
                        self.agent.fleetmanagers = json.loads(msg.body)
                        logger.debug("{} Get fleet managers {}".format(self.agent.name, self.agent.fleetmanagers))
                        return
                    elif performative == CANCEL_PERFORMATIVE:
                        logger.debug("Cancellation of request for {} information".format(self.agent.type_service))
                        return

        # if self.agent.status == CUSTOMER_WAITING:
            # await self.send_request(content={})

        msg = await self.receive(timeout=60)

        if msg:
            performative = msg.get_metadata("performative")
            transport_id = msg.sender
            if performative == PROPOSE_PERFORMATIVE:
                if self.agent.status == CUSTOMER_WAITING:
                    logger.debug(
                        "Customer {} received proposal from transport {}".format(self.agent.name, transport_id))
                    await self.accept_transport(transport_id)
                    self.agent.status = CUSTOMER_ASSIGNED
                else:
                    await self.refuse_transport(transport_id)

            elif performative == CANCEL_PERFORMATIVE:
                if self.agent.transport_assigned == str(transport_id):
                    logger.warning(
                        "Customer {} received a CANCEL from Transport {}.".format(self.agent.name, transport_id))
                    self.agent.status = CUSTOMER_WAITING
