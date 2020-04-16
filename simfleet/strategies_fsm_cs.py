import json

from loguru import logger
from spade.behaviour import State, FSMBehaviour
from spade.message import Message
from simfleet.customer_cs import CustomerStrategyBehaviour
from simfleet.fleetmanager import FleetManagerStrategyBehaviour
from simfleet.helpers import PathRequestException, distance_in_meters
from simfleet.protocol import REQUEST_PERFORMATIVE, ACCEPT_PERFORMATIVE, REFUSE_PERFORMATIVE, REQUEST_PROTOCOL, \
    INFORM_PERFORMATIVE, CANCEL_PERFORMATIVE, PROPOSE_PERFORMATIVE, QUERY_PROTOCOL
from simfleet.transport_cs import TransportStrategyBehaviour
from simfleet.utils import TRANSPORT_WAITING, TRANSPORT_WAITING_FOR_APPROVAL, TRANSPORT_MOVING_TO_CUSTOMER, \
    TRANSPORT_NEEDS_CHARGING, TRANSPORT_MOVING_TO_STATION, TRANSPORT_IN_STATION_PLACE, TRANSPORT_CHARGING, \
    TRANSPORT_CHARGED, CUSTOMER_WAITING, CUSTOMER_ASSIGNED, TRANSPORT_BOOKED, TRANSPORT_MOVING_TO_DESTINATION, \
    CUSTOMER_WAITING_FOR_APPROVAL, CUSTOMER_MOVING_TO_TRANSPORT, CUSTOMER_IN_TRANSPORT, CUSTOMER_IN_DEST


################################################################
#                                                              #
#                     FleetManager Strategy                    #
#                                                              #
################################################################
class SendAvailableTransportsBehaviour(FleetManagerStrategyBehaviour):
    """
    Awaits customer's requests and replies with the lest of available transports
    """

    async def run(self):
        if not self.agent.registration:
            await self.send_registration()

        msg = await self.receive(timeout=5)
        logger.debug("Manager received message: {}".format(msg))
        if msg:
            protocol = msg.get_metadata("protocol")
            if protocol == QUERY_PROTOCOL:
                performative = msg.get_metadata("performative")
                if performative == REQUEST_PERFORMATIVE:
                    body = json.loads(msg.body)
                    reply = Message()
                    # get list of available transport agents
                    available_transports = [(t, t.get("current_pos")) for t in self.get_transport_agents() if
                                            t.status == TRANSPORT_WAITING]
                    # add list to content
                    content = {"transports": available_transports}
                    reply.to(body["customer_id"])
                    reply.set_metadata("protocol", QUERY_PROTOCOL)
                    reply.set_metadata("performative", REQUEST_PERFORMATIVE)
                    reply.body = content
                    # reply to sender (through send() or a custom method)
                    await self.send(reply)
                    logger.debug("Fleet manager sent list of transports to customer {}".format(body["customer_id"]))


################################################################
#                                                              #
#                     Transport Strategy                       #
#                                                              #
################################################################
class TransportWaitingState(TransportStrategyBehaviour, State):
    # TODO
    async def on_start(self):
        await super().on_start()
        self.agent.status = TRANSPORT_WAITING
        logger.debug("{} in Transport Waiting State".format(self.agent.jid))

    async def run(self):
        msg = await self.receive(timeout=60)
        if not msg:
            self.set_next_state(TRANSPORT_WAITING)
            return
        logger.debug("Transport {} received: {}".format(self.agent.jid, msg.body))
        content = json.loads(msg.body)
        performative = msg.get_metadata("performative")
        if performative == REQUEST_PERFORMATIVE:
            await self.accept_customer(content["customer_id"])
            self.set_next_state(TRANSPORT_BOOKED)
            return
        else:
            self.set_next_state(TRANSPORT_WAITING)
            return


class TransportBookedState(TransportStrategyBehaviour, State):
    # TODO
    async def on_start(self):
        await super().on_start()
        self.agent.status = TRANSPORT_BOOKED
        logger.debug("{} in Transport Booked State".format(self.agent.jid))

    async def run(self):
        msg = await self.receive(timeout=60)
        if not msg:
            self.set_next_state(TRANSPORT_WAITING)
            return
        logger.debug("Transport {} received: {}".format(self.agent.jid, msg.body))
        content = json.loads(msg.body)
        performative = msg.get_metadata("performative")
        # We can receive 3 types of messages
        # 1) Another booking request
        if performative == REQUEST_PERFORMATIVE:
            await self.refuse_customer(content["customer_id"])
            self.set_next_state(TRANSPORT_BOOKED)
            return
        # 2) Customer cancels request
        elif performative == CANCEL_PERFORMATIVE:
            if self.agent.get("current_customer") == content["customer_id"]:
                await self.deasign_customer()
                self.set_next_state(TRANSPORT_WAITING)
                return
        # 3) Customer informs that they are in my position
        elif performative == INFORM_PERFORMATIVE:
            try:
                await self.pick_up_customer(content["customer_id"], content["origin"], content["dest"])
                # CHECK APPROPRIATE UPDATE OF STATUS
                self.set_next_state(TRANSPORT_MOVING_TO_DESTINATION)
                return
            except PathRequestException:
                logger.error("Transport {} could not get a path to customer {}. Cancelling..."
                             .format(self.agent.name, content["customer_id"]))
                await self.refuse_customer(content["customer_id"])
                self.set_next_state(TRANSPORT_WAITING)
                return
            except Exception as e:
                logger.error("Unexpected error in transport {}: {}".format(self.agent.name, e))
                await self.refuse_customer(content["customer_id"])
                self.set_next_state(TRANSPORT_WAITING)
                return
        else:
            logger.warning("Transport {} received an unexpected message from {} with content {}"
                           .format(self.agent.name, msg.sender, content))
            self.set_next_state(TRANSPORT_BOOKED)
            return


class TransportMovingToDestinationState(TransportStrategyBehaviour, State):
    # TODO
    async def on_start(self):
        await super().on_start()
        self.agent.status = TRANSPORT_MOVING_TO_DESTINATION
        logger.debug("{} in Transport Moving To Destination State".format(self.agent.jid))

    # Blocks the strategy behaviour (not the Transport Agent) until the transport agent has
    # dropped the customer in its destination
    async def run(self):
        # Reset internal flag to False. coroutines calling
        # wait() will block until set() is called
        self.agent.customer_in_transport_event.clear()
        # Registers an observer callback to be run when the "customer_in_transport" is changed
        self.agent.watch_value("customer_in_transport", self.agent.customer_in_transport_callback)
        # block behaviour until another coroutine calls set()
        await self.agent.customer_in_transport_event.wait()
        return self.set_next_state(TRANSPORT_WAITING)


class FSMTransportStrategyBehaviour(FSMBehaviour):
    def setup(self):
        # Create states
        self.add_state(TRANSPORT_WAITING, TransportWaitingState(), initial=True)
        self.add_state(TRANSPORT_BOOKED, TransportBookedState())
        self.add_state(TRANSPORT_MOVING_TO_DESTINATION, TransportMovingToDestinationState())

        # Create transitions
        self.add_transition(TRANSPORT_WAITING, TRANSPORT_WAITING)  # waiting for messages
        self.add_transition(TRANSPORT_WAITING, TRANSPORT_BOOKED)  # booking

        self.add_transition(TRANSPORT_BOOKED, TRANSPORT_BOOKED)  # waiting for customer to arrive and messages
        self.add_transition(TRANSPORT_BOOKED, TRANSPORT_WAITING)  # booking cancelled
        self.add_transition(TRANSPORT_BOOKED, TRANSPORT_MOVING_TO_DESTINATION)  # customer arrived, start movement

        self.add_transition(TRANSPORT_MOVING_TO_DESTINATION, TRANSPORT_WAITING)  # transport is free again


################################################################
#                                                              #
#                       Customer Strategy                      #
#                                                              #
################################################################
class CustomerWaitingState(CustomerStrategyBehaviour, State):

    async def on_start(self):
        await super().on_start()

    async def run(self):
        # Get fleet managers
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
                        self.set_next_state(CUSTOMER_WAITING)
                        return
                    elif performative == CANCEL_PERFORMATIVE:
                        logger.debug("Cancellation of request for {} information".format(self.agent.type_service))
                        self.set_next_state(CUSTOMER_WAITING)
                        return

        # Get list of available transports
        if not self.agent.available_transports:
            await self.send_get_transports()

            msg = await self.receive(timeout=5)
            if msg:
                content = json.loads(msg.body)
                protocol = msg.get_metadata("protocol")
                if protocol == QUERY_PROTOCOL:
                    performative = msg.get_metadata("performative")
                    if performative == REQUEST_PERFORMATIVE:
                        self.agent.available_transports = content["transports"]
                        logger.debug("Customer {} got list of available transports {}".format(self.agent.name,
                                                                                              self.agent.available_transports))
                        self.set_next_state(CUSTOMER_WAITING)
                        return
                    else:
                        logger.warning("Customer {} received an unexpected message from {} with content {}"
                                       .format(self.agent.name, msg.sender, content))
                        self.set_next_state(CUSTOMER_WAITING)
                        return

        else:  # Send proposal
            closest_transport = min(self.agent.available_transports,
                                    key=lambda x: distance_in_meters(x[1], self.agent.get_position()))
            logger.debug("Closest transport: {}".format(closest_transport))
            transport_id = closest_transport[0]
            # delete that transport from the available_transports list
            self.agent.available_transports.remove(closest_transport)
            # self.agent.available_transports = [x for x in self.agent.available_transports if x[0] != transport_id]
            # Save temporarily data of closest transport in case it accepts the booking request
            # TODO
            if closest_transport is not None:
                await self.send_proposal(transport_id)  # maybe str(transport_id)
                self.set_next_state(CUSTOMER_WAITING_FOR_APPROVAL)
                return
            else:
                logger.warning("Closest transport to customer {} was None".format(self.agent.name))
                self.agent.available_transports = []
                self.set_next_state(CUSTOMER_WAITING)
                return


class CustomerWaitingForApprovalState(CustomerStrategyBehaviour, State):
    # TODO
    async def on_start(self):
        await super().on_start()

    async def run(self):
        msg = await self.receive(timeout=60)
        if not msg:
            self.set_next_state(CUSTOMER_WAITING_FOR_APPROVAL)
            return
        content = json.loads(msg.body)
        performative = msg.get_metadata("performative")
        if performative == ACCEPT_PERFORMATIVE:
            try:
                logger.debug("Customer {} booked transport {}".format(self.agent.name,
                                                                      content["transport_id"]))
                await self.go_to_transport(content["transport_id"], content["origin"], content["dest"])
                self.set_next_state(CUSTOMER_MOVING_TO_TRANSPORT)
                return
            except PathRequestException:
                logger.error("Customer {} could not get a path to customer {}. Cancelling..."
                             .format(self.agent.name, content["transport_id"]))
                await self.cancel_proposal(content["transport_id"])
                self.set_next_state(CUSTOMER_WAITING)
                return
            except Exception as e:
                logger.error("Unexpected error in customr {}: {}".format(self.agent.name, e))
                await self.cancel_proposal(content["transport_id"])
                self.set_next_state(CUSTOMER_WAITING)
                return

        elif performative == REFUSE_PERFORMATIVE:
            logger.debug("Customer {} got refusal from transport".format(self.agent.name))
            self.set_next_state(CUSTOMER_WAITING)
            return

        else:
            self.set_next_state(CUSTOMER_WAITING_FOR_APPROVAL)
            return


class CustomerMovingToTransportState(CustomerStrategyBehaviour, State):
    # TODO
    async def on_start(self):
        await super().on_start()

    async def run(self):
        return


class CustomerInTransportState(CustomerStrategyBehaviour, State):
    # TODO
    async def on_start(self):
        await super().on_start()

    async def run(self):
        return


class CustomerInDestState(CustomerStrategyBehaviour, State):
    # TODO
    async def on_start(self):
        await super().on_start()

    async def run(self):
        return


class FSMCustomerStrategyBehaviour(FSMBehaviour):
    def setup(self):
        # Create states
        self.add_state(CUSTOMER_WAITING, CustomerWaitingState(), initial=True)
        self.add_state(CUSTOMER_WAITING_FOR_APPROVAL, CustomerWaitingForApprovalState())
        self.add_state(CUSTOMER_MOVING_TO_TRANSPORT, CustomerMovingToTransportState())
        self.add_state(CUSTOMER_IN_TRANSPORT, CustomerInTransportState())
        self.add_state(CUSTOMER_IN_DEST, CustomerInDestState())

        # Create transitions
        self.add_transition(CUSTOMER_WAITING, CUSTOMER_WAITING)  # get list of transports
        self.add_transition(CUSTOMER_WAITING, CUSTOMER_WAITING_FOR_APPROVAL)  # send booking proposal

        self.add_transition(CUSTOMER_WAITING_FOR_APPROVAL, CUSTOMER_WAITING)  # booking is rejected
        self.add_transition(CUSTOMER_WAITING_FOR_APPROVAL,
                            CUSTOMER_WAITING_FOR_APPROVAL)  # waiting for approval message
        self.add_transition(CUSTOMER_WAITING_FOR_APPROVAL, CUSTOMER_MOVING_TO_TRANSPORT)  # booking accepted

        self.add_transition(CUSTOMER_MOVING_TO_TRANSPORT,
                            CUSTOMER_IN_TRANSPORT)  # arrived to transport, picked up by it

        self.add_transition(CUSTOMER_IN_TRANSPORT, CUSTOMER_IN_DEST)  # arrived to destination
