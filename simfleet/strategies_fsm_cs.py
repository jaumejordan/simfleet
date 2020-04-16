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
                    available_transports = [t for t in self.get_transport_agents() if t.status == TRANSPORT_WAITING]
                    # add list to content
                    content = {"transports": available_transports}
                    reply.to(body["customer_id"])
                    reply.set_metadata("protocol", QUERY_PROTOCOL)
                    reply.set_metadata("performative", INFORM_PERFORMATIVE)
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

    async def run(self):
        return


class TransportBookedState(TransportStrategyBehaviour, State):
    # TODO
    async def on_start(self):
        await super().on_start()

    async def run(self):
        return


class TransportMovingToDestinationState(TransportStrategyBehaviour, State):
    # TODO
    async def on_start(self):
        await super().on_start()

    async def run(self):
        return


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
    # Get fleet managers
    # Get list of available transports
    # Send proposal
    # TODO
    async def on_start(self):
        await super().on_start()

    async def run(self):
        return


class CustomerWaitingForApprovalState(CustomerStrategyBehaviour, State):
    # TODO
    async def on_start(self):
        await super().on_start()

    async def run(self):
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
