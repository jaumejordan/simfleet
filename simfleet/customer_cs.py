import asyncio
import json
import time
from asyncio import CancelledError
from collections import defaultdict

from loguru import logger
from spade.agent import Agent
from spade.behaviour import CyclicBehaviour, PeriodicBehaviour
from spade.message import Message
from spade.template import Template

from simfleet.helpers import random_position, distance_in_meters, kmh_to_ms, PathRequestException, AlreadyInDestination
from simfleet.protocol import TRAVEL_PROTOCOL, QUERY_PROTOCOL, REQUEST_PERFORMATIVE, REQUEST_PROTOCOL, \
    REFUSE_PERFORMATIVE, CANCEL_PERFORMATIVE, PROPOSE_PERFORMATIVE, INFORM_PERFORMATIVE
from simfleet.utils import CUSTOMER_WAITING, CUSTOMER_IN_DEST, CUSTOMER_IN_TRANSPORT, \
    TRANSPORT_IN_CUSTOMER_PLACE, CUSTOMER_LOCATION, StrategyBehaviour, request_path, chunk_path

ONESECOND_IN_MS = 1000


class CustomerAgent(Agent):
    """
    Defines the Customer Agent's attributes.
    Contains basic methods for agent setup and configuration.
    """

    def __init__(self, agentjid, password):
        super().__init__(agentjid, password)
        self.__observers = defaultdict(list)
        self.agent_id = None
        self.strategy = None
        self.icon = None
        self.running_strategy = False
        self.fleet_type = None
        self.fleetmanagers = None
        self.route_id = None
        self.status = CUSTOMER_WAITING
        self.current_pos = None
        self.dest = None
        self.port = None
        self.transport_assigned = None
        self.init_time = None
        self.waiting_for_pickup_time = None
        self.pickup_time = None
        self.end_time = None
        self.stopped = False
        self.ready = False
        self.is_launched = False

        # Attributes for movement
        self.available_transports = []
        self.set("current_transport", None)
        self.current_transport_pos = None
        self.set("current_pos", None)
        self.dest = None
        self.set("path", None)
        self.chunked_path = None
        self.set("speed_in_kmh", 1000)  # MODIFIABLE, NOW MADE A THIRD OF TRANSPORT SPEED
        self.animation_speed = ONESECOND_IN_MS
        self.distances = []
        self.durations = []

        self.directory_id = None
        # type of the FleetManager (I think)
        self.type_service = "taxi"
        self.request = "transport"

        # ATRIBUTES FOR EVENT AND CALLBACK MANAGEMENT
        # self.__observers = defaultdict(list)
        # Customer arrived to transport event. Triggers when the customer stops its
        # MovingBehavior because it has arrived to the booked transport's position
        self.set("arrived_to_transport", None)

        self.arrived_to_transport_event = asyncio.Event(loop=self.loop)

        def arrived_to_transport_callback(old, new):
            if not self.arrived_to_transport_event.is_set() and new is True:
                self.arrived_to_transport_event.set()

        self.arrived_to_transport_callback = arrived_to_transport_callback

    async def setup(self):
        # CHECK IF IT NEEDS MODIFICATION
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

    def set(self, key, value):
        """
        Modifies a value in the defaultsdic, taking into account the observers it may have
        and triggering the appropriate callbacks
        """
        old = self.get(key)
        super().set(key, value)
        if key in self.__observers:
            for callback in self.__observers[key]:
                callback(old, value)

    def watch_value(self, key, callback):
        """
        Registers an observer callback to be run when a value is changed

        Args:
            key (str): the name of the value
            callback (function): a function to be called when the value changes. It receives two arguments: the old and the new value.
        """
        self.__observers[key].append(callback)

    def run_strategy(self):
        # CHECK IF IT NEEDS MODIFICATION
        """import json
        Runs the strategy for the customer agent.
        """
        if not self.running_strategy:
            template1 = Template()
            template1.set_metadata("protocol", REQUEST_PROTOCOL)
            template2 = Template()
            template2.set_metadata("protocol", QUERY_PROTOCOL)
            self.add_behaviour(self.strategy(), template1 | template2)
            self.running_strategy = True

    def set_id(self, agent_id):
        """
        Sets the agent identifier
        Args:
            agent_id (str): The new Agent Id
        """
        self.agent_id = agent_id

    def set_icon(self, icon):
        self.icon = icon

    def set_fleet_type(self, fleet_type):
        """
        Sets the type of fleet to be used.

        Args:
            fleet_type (str): the type of the fleet to be used
        """
        self.fleet_type = fleet_type

    def set_fleetmanager(self, fleetmanagers):
        """
        Sets the fleetmanager JID address
        Args:
            fleetmanagers (str): the fleetmanager jid

        """
        self.fleetmanagers = fleetmanagers

    def set_route_agent(self, route_id):
        """
        Sets the route agent JID address
        Args:
            route_id (str): the route agent jid

        """
        self.route_id = route_id

    def set_directory(self, directory_id):
        """
        Sets the directory JID address
        Args:
            directory_id (str): the DirectoryAgent jid

        """
        self.directory_id = directory_id

    def set_initial_position(self, coords):
        self.current_pos = coords
        self.set("current_pos", coords)
        logger.debug("Customer {} position is {}".format(self.agent_id, self.get("current_pos")))

    async def set_position(self, coords=None):
        """
        Sets the position of the transport. If no position is provided it is located in a random position.

        Args:
            coords (list): a list coordinates (longitude and latitude)
        """
        # MUST BE MODIFIED TO ADAPT IT FOR CUSTOMER MOVEMENT
        if coords:
            self.set("current_pos", coords)
        else:
            self.set("current_pos", random_position())
        logger.debug("Customer {} position is {}".format(self.agent_id, self.get("current_pos")))
        if self.is_in_destination():
            logger.info("Customer {} has arrived to destination. Status: {}".format(self.agent_id, self.status))
            await self.arrived_to_transport()

    def get_position(self):
        """
        Returns the current position of the customer.

        Returns:
            list: the coordinates of the current position of the customer (lon, lat)
        """
        # return self.current_pos
        return self.get("current_pos")

    def set_target_position(self, coords=None):
        """
        Sets the target position of the customer (i.e. its destination).
        If no position is provided the destination is setted to a random position.

        Args:
            coords (list): a list coordinates (longitude and latitude)
        """
        if coords:
            self.dest = coords
        else:
            self.dest = random_position()
        logger.debug("Customer {} target position is {}".format(self.agent_id, self.dest))

    def is_in_destination(self):
        """
        Checks if the customer has arrived to its destination.

        Returns:
            bool: whether the customer is at its destination or not
        """
        return self.status == CUSTOMER_IN_DEST or self.get_position() == self.dest

    def set_speed(self, speed_in_kmh):
        """
        Sets the speed of the transport.

        Args:
            speed_in_kmh (float): the speed of the transport in km per hour
        """
        self.set("speed_in_kmh", speed_in_kmh)

    async def request_path(self, origin, destination):
        """
        Requests a path between two points (origin and destination) using the RouteAgent service.

        Args:
            origin (list): the coordinates of the origin of the requested path
            destination (list): the coordinates of the end of the requested path

        Returns:
            list, float, float: A list of points that represent the path from origin to destination, the distance and the estimated duration
        """
        return await request_path(self, origin, destination, self.route_id)

    def total_time(self):
        """
        Returns the time since the customer was activated until it reached its destination.

        Returns:
            float: the total time of the customer's simulation.
        """
        if self.init_time and self.end_time:
            return self.end_time - self.init_time
        else:
            return None

    def get_waiting_time(self):
        """
        Returns the time that the agent was waiting for a transport, from its creation until it gets into a transport.

        Returns:
            float: The time the customer was waiting.
        """
        if self.init_time:
            if self.pickup_time:
                t = self.pickup_time - self.init_time
            elif not self.stopped:
                t = time.time() - self.init_time
                self.waiting_for_pickup_time = t
            else:
                t = self.waiting_for_pickup_time
            return t
        return None

    def get_pickup_time(self):
        """
        Returns the time that the customer was waiting to be picked up since it has been assigned to a transport.

        Returns:
            float: The time that the customer was waiting to a transport since it has been assigned.
        """
        if self.pickup_time:
            return self.pickup_time - self.waiting_for_pickup_time
        return None

    def to_json(self):
        """
        Serializes the main information of a customer agent to a JSON format.
        It includes the id of the agent, its current position, the destination coordinates of the agent,
        the current status, the transport that it has assigned (if any) and its waiting time.

        Returns:
            dict: a JSON doc with the main information of the customer.

            Example::

                {
                    "id": "cphillips",
                    "position": [ 39.461327, -0.361839 ],
                    "dest": [ 39.460599, -0.335041 ],
                    "status": 24,
                    "transport": "ghiggins@127.0.0.1",
                    "waiting": 13.45
                }
        """
        t = self.get_waiting_time()
        return {
            "id": self.agent_id,
            "position": [float("{0:.6f}".format(coord)) for coord in self.current_pos],
            "dest": [float("{0:.6f}".format(coord)) for coord in self.dest],
            "status": self.status,
            "transport": self.transport_assigned.split("@")[0] if self.transport_assigned else None,
            "waiting": float("{0:.2f}".format(t)) if t else None,
            "icon": self.icon
        }

    async def cancel_transport(self, data=None):
        """
        Sends a message to the current booked transport to cancel the assignment.

        Args:
            data (dict, optional): Complementary info about the cancellation
        """
        # TRIGGERED WHEN EXCEPTION TRYING TO MOVE TO TRANSPORTS DESTINATION
        # COPIED AND MODIFIED FROM transport.py, MIGHT NEED FURTHER MODIFICATION
        logger.error("Customer {} could not get a path to transport {}.".format(self.agent_id,
                                                                                self.get("current_transport")))
        if data is None:
            data = {}
        reply = Message()
        reply.to = self.get("current_transport")
        reply.set_metadata("protocol", REQUEST_PROTOCOL)
        reply.set_metadata("performative", CANCEL_PERFORMATIVE)
        reply.body = json.dumps(data)
        logger.debug("Customer {} sent cancel proposal to transport {}".format(self.agent_id,
                                                                               self.get("current_transport")))
        await self.send(reply)

    async def arrived_to_transport(self):
        """
        Informs that the customer has arrived to its booked transport position.
        It must change the appropriate value to trigger a callback
        """
        # TODO
        logger.info("Customer {} arrived to the transport {} position".format(self.name,
                                                                              self.get("current_transport")))
        self.set("arrived_to_transport", True)

    async def move_to(self, dest):
        """
        Moves the customer to a new destination.

        Args:
            dest (list): the coordinates of the new destination (in lon, lat format)

        Raises:
             AlreadyInDestination: if the transport is already in the destination coordinates.
        """
        # MUST BE MODIFIED TO ADAPT IT FOR CUSTOMER MOVEMENT TO BOOKED TRANSPORT
        logger.info("---------------Customer {} MOVING TO transport {}".format(self.name,
                                                                               self.get("current_transport")))
        if self.get("current_pos") == dest:
            raise AlreadyInDestination
        counter = 5
        path = None
        distance, duration = 0, 0
        while counter > 0 and path is None:
            logger.info("Requesting path from {} to {}".format(self.get("current_pos"), dest))
            path, distance, duration = await self.request_path(self.get("current_pos"), dest)
            counter -= 1
        if path is None:
            raise PathRequestException("Error requesting route.")

        self.set("path", path)
        try:
            self.chunked_path = chunk_path(path, self.get("speed_in_kmh"))
        except Exception as e:
            logger.error("Exception chunking path {}: {}".format(path, e))
            raise PathRequestException
        self.dest = dest
        self.distances.append(distance)
        self.durations.append(duration)
        behav = self.MovingBehaviour(period=1)
        self.add_behaviour(behav)

    async def step(self):
        """
        Advances one step in the simulation
        """
        if self.chunked_path:
            _next = self.chunked_path.pop(0)
            distance = distance_in_meters(self.get_position(), _next)
            self.animation_speed = distance / kmh_to_ms(self.get("speed_in_kmh")) * ONESECOND_IN_MS
            await self.set_position(_next)

    class MovingBehaviour(PeriodicBehaviour):
        """
        This is the internal behaviour that manages the movement of the transport.
        It is triggered when the transport has a new destination and the periodic tick
        is recomputed at every step to show a fine animation.
        This moving behaviour includes to update the transport coordinates as it
        moves along the path at the specified speed.
        """

        async def run(self):
            logger.warning("Running moving behaviour")
            await self.agent.step()
            self.period = self.agent.animation_speed / ONESECOND_IN_MS
            if self.agent.is_in_destination():
                self.agent.remove_behaviour(self)


class TravelBehaviour(CyclicBehaviour):
    """
    This is a modification of the internal behaviour that manages the movement of the
    customer. It will be triggered once the transport informs the customer it is in
    its position. This will only happen after the customer arrives to the transport
    location and informs it first.
    """

    async def on_start(self):
        logger.debug("Customer {} started TravelBehavior.".format(self.agent.name))

    async def run(self):
        try:
            msg = await self.receive(timeout=5)
            if not msg:
                return
            content = json.loads(msg.body)
            logger.debug("Customer {} informed of: {}".format(self.agent.name, content))
            if "status" in content:
                status = content["status"]
                # Transport informs me that I can go in
                if status == TRANSPORT_IN_CUSTOMER_PLACE:
                    self.agent.status = CUSTOMER_IN_TRANSPORT
                    logger.info("Customer {} in transport.".format(self.agent.name))
                    self.agent.pickup_time = time.time()
                # Transport informs me that we have reached our destination
                elif status == CUSTOMER_IN_DEST:
                    self.agent.status = CUSTOMER_IN_DEST
                    self.agent.end_time = time.time()
                    logger.info("Customer {} arrived to destination after {} seconds."
                                .format(self.agent.name, self.agent.total_time()))
                # Move the customer exactly to the coordinates where the transport expects it to be
                elif status == CUSTOMER_LOCATION:
                    coords = content["location"]
                    self.agent.set_position(coords)
        except CancelledError:
            logger.debug("Cancelling async tasks...")
        except Exception as e:
            logger.error("EXCEPTION in Travel Behaviour of Customer {}: {}".format(self.agent.name, e))


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
        """
        Initializes the logger and timers. Call to parent method if overloaded.
        """
        logger.debug("Strategy {} started in customer {}".format(type(self).__name__, self.agent.name))
        # self.agent.init_time = time.time()

    async def send_get_managers(self, content=None):
        """
        Sends an ``spade.message.Message`` to the DirectoryAgent to request a managers.
        It uses the QUERY_PROTOCOL and the REQUEST_PERFORMATIVE.
        If no content is set a default content with the type_service that needs
        Args:
            content (dict): Optional content dictionary
        """
        if content is None or len(content) == 0:
            content = self.agent.fleet_type
        msg = Message()
        msg.to = str(self.agent.directory_id)
        msg.set_metadata("protocol", QUERY_PROTOCOL)
        msg.set_metadata("performative", REQUEST_PERFORMATIVE)
        msg.body = content
        await self.send(msg)
        logger.debug("Customer {} asked for managers to directory {} for type {}.".format(self.agent.name,
                                                                                          self.agent.directory_id,
                                                                                          self.agent.type_service))

    async def send_get_transports(self, content=None):  # new
        if content is None or len(content) == 0:
            content = self.agent.request
        msg = Message()
        msg.to = str(self.agent.directory_id)
        msg.set_metadata("protocol", QUERY_PROTOCOL)
        msg.set_metadata("performative", REQUEST_PERFORMATIVE)
        msg.body = content
        await self.send(msg)
        logger.debug("Customer {} asked for transports to Directory {} for type {}.".format(self.agent.name,
                                                                                            self.agent.directory_id,
                                                                                            self.agent.request))

    async def send_get_transports2(self, content=None):
        """
        Sends an ``spade.message.Message`` to the FleetManager to request a list of available transports.
        It uses the QUERY_PROTOCOL and the REQUEST_PERFORMATIVE.
        If no content is set a default content with the type_service that needs
        Args:
            content (dict): Optional content dictionary
        """
        # TODO
        if content is None or len(content) == 0:
            content = {"customer_id": self.agent.jid}
        if self.agent.fleetmanagers is not None:
            for fleetmanager in self.agent.fleetmanagers.keys():
                msg = Message()
                msg.to = str(fleetmanager)
                msg.set_metadata("protocol", REQUEST_PROTOCOL)
                msg.set_metadata("performative", REQUEST_PERFORMATIVE)
                # msg.set_metadata("protocol", QUERY_PROTOCOL)
                # msg.set_metadata("performative", REQUEST_PERFORMATIVE)
                msg.body = json.dumps(content)
                await self.send(msg)
            logger.info("Customer {} asked for a available transports to {}.".format(self.agent.name, fleetmanager))
        else:
            logger.warning("Customer {} has no fleet managers.".format(self.agent.name))

    # async def send_booking_request(self, content=None):
    #     """
    #     Checks its available_transports list and pops the closest one.
    #     Sends a ``spade.message.Mesade`` to the closes transport request a booking.
    #     It uses the REQUEST_PROTOCOL and the PROPOSE_PERFORMATIVE.
    #     If no content is set a default content with the customer_id,
    #     origin and target coordinates is used.
    #
    #     Args:
    #         content (dict): Optional content dictionary
    #     """
    #     # TODO

    async def send_proposal(self, transport_id, content=None):
        """
        Send a ``spade.message.Message`` with a proposal to a customer to pick up him.
        If the content is empty the proposal is sent without content.

        Args:
            transport_id (str): the id of the customer
            content (dict, optional): the optional content of the message
        """
        # COPIED FROM transport.py, CHECK IF NEEDS MODIFICATION
        reply = Message()
        reply.to = transport_id
        reply.set_metadata("protocol", REQUEST_PROTOCOL)
        reply.set_metadata("performative", PROPOSE_PERFORMATIVE)
        if content is None:
            content = {
                "customer_id": str(self.agent.jid),
            }
        reply.body = json.dumps(content)
        await self.send(reply)
        logger.info("Customer {} sent booking to transport {}".format(self.agent.name, transport_id))

    async def cancel_proposal(self, transport_id, content=None):
        """
        Sends an ``spade.message.Message`` to a transport to cancel its booking.
        It uses the REQUEST_PROTOCOL and the REFUSE_PERFORMATIVE.

        Args:
            transport_id (str): The Agent JID of the transport
        """
        # COPIED FROM transport.py, CHECK IF NEEDS MODIFICATION
        reply = Message()
        reply.to = transport_id
        reply.set_metadata("protocol", REQUEST_PROTOCOL)
        reply.set_metadata("performative", CANCEL_PERFORMATIVE)
        if content is None:
            content = {
                "customer_id": str(self.agent.jid),
            }
        reply.body = json.dumps(content)
        await self.send(reply)
        logger.info("Customer {} sent cancel booking to transport {}".format(self.agent.name, transport_id))

    async def go_to_transport(self, transport_id, dest):
        logger.info("Customer {} on route to transport {}".format(self.agent.name, transport_id))
        self.agent.set("current_transport", transport_id)
        self.agent.current_transport_pos = dest
        logger.info("go_to_transport:::{} {}".format(self.get("current_transport"), self.agent.current_transport_pos))
        try:
            await self.agent.move_to(self.agent.current_transport_pos)
        except AlreadyInDestination:
            await self.agent.arrived_to_transport()

    async def inform_transport(self, content=None):
        """
        Sends a ``spade.message.Mesade`` to the booked transport.
        It uses the ???_PROTOCOL and the ???_PERFORMATIVE.
        This method is used to inform the transport that the customer agent is in its position.
        The transport will be waiting for this message and, upon receiving it, it will pick the
        customer up and start to move.

        Args:
            content (dict): Optional content dictionary
        """
        # NOT SURE IF THIS WILL BE PERFORMED INSIDE arrived_to_transport OR HERE
        # DON'T IMPLEMENT BY NOW
        # ++++++++++++ IMPORTANT: SEND AS "origin": THE COORDINATES OF MY CURRENT POSITION
        # ++++++++++++ WHICH IS ALSO THE TRANSPORT'S POSITION
        msg = Message()
        msg.to = self.get("current_transport")
        msg.set_metadata("protocol", REQUEST_PROTOCOL)
        msg.set_metadata("performative", INFORM_PERFORMATIVE)
        if content is None:
            content = {
                "customer_id": str(self.agent.jid),
                "origin": self.get("current_pos"),
                "dest": self.agent.dest
            }
        msg.body = json.dumps(content)
        await self.send(msg)
        logger.info("Customer {} informed transport {} that they are in its position".format(self.agent.name,
                                                                                             self.get(
                                                                                                 "current_transport")))

    async def run(self):
        raise NotImplementedError
