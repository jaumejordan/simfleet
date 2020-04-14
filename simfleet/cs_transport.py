import asyncio
import json
import time
from asyncio import CancelledError
from collections import defaultdict

from loguru import logger
from spade.agent import Agent
from spade.behaviour import PeriodicBehaviour, CyclicBehaviour
from spade.message import Message
from spade.template import Template

from simfleet.protocol import REGISTER_PROTOCOL
from simfleet.utils import StrategyBehaviour


class TransportAgent(Agent):

    def __init__(self, agentjid, password):
        super().__init__(agentjid, password)

    async def setup(self):
        try:
            template = Template()
            template.set_metadata("protocol", REGISTER_PROTOCOL)
            register_behaviour = RegistrationBehaviour()
            self.add_behaviour(register_behaviour, template)
            while not self.has_behaviour(register_behaviour):
                logger.warning("Transport {} could not create RegisterBehaviour. Retrying...".format(self.agent_id))
                self.add_behaviour(register_behaviour, template)
            self.ready = True
        except Exception as e:
            logger.error("EXCEPTION creating RegisterBehaviour in Transport {}: {}".format(self.agent_id, e))


class RegistrationBehaviour(CyclicBehaviour):
    async def on_start(self):
        logger.debug("Strategy {} started in transport".format(type(self).__name__))


class TransportStrategyBehaviour(StrategyBehaviour):
    """
    Class from which to inherit to create a transport strategy.
    You must overload the ```run`` coroutine

    Helper functions:
        * ``pick_up_customer``
        * ``send_proposal``
        * ``cancel_proposal``
    """

    async def on_start(self):
        logger.debug("Strategy {} started in transport {}".format(type(self).__name__, self.agent.name))
        self.agent.total_waiting_time = 0.0
