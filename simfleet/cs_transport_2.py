import json
import time
from asyncio import CancelledError

from loguru import logger
from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.message import Message
from spade.template import Template

from simfleet.protocol import TRAVEL_PROTOCOL
from simfleet.utils import StrategyBehaviour


class CustomerAgent(Agent):
    def __init__(self, agentjid, password):
        super().__init__(agentjid, password)

    async def setup(self):
        try:
            template = Template()
            template.set_metadata("protocol", TRAVEL_PROTOCOL)
            travel_behaviour = TravelBehaviour()
            self.add_behaviour(travel_behaviour, template)
            while not self.has_behaviour(travel_behaviour):
                logger.warning("Customer {} could not create TravelBehaviour. Retrying...".format(self.agent_id))
                self.add_behaviour(travel_behaviour, template)
            self.ready = True
        except Exception as e:
            logger.error("EXCEPTION creating TravelBehaviour in Customer {}: {}".format(self.agent_id, e))

class TravelBehaviour(CyclicBehaviour):
    """
    This is the internal behaviour that manages the movement of the customer.
    It is triggered when the transport informs the customer that it is going to the
    customer's position until the customer is dropped in its destination.
    """

    async def on_start(self):
        logger.debug("Customer {} started TravelBehavior.".format(self.agent.name))

    async def run(self):
        # TODO

class CustomerStrategyBehaviour(StrategyBehaviour):
    """
    Class from which to inherit to create a transport strategy.
    You must overload the ``run`` coroutine

    Helper functions:
        * ``send_request``
        * ``accept_transport``
        * ``refuse_transport``
    """

    async def on_start(self):
