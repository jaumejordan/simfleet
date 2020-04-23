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

from simfleet.helpers import PathRequestException, AlreadyInDestination, random_position, distance_in_meters, kmh_to_ms
from simfleet.protocol import REGISTER_PROTOCOL, REQUEST_PROTOCOL, QUERY_PROTOCOL, ACCEPT_PERFORMATIVE, TRAVEL_PROTOCOL, \
    INFORM_PERFORMATIVE, CANCEL_PERFORMATIVE, REQUEST_PERFORMATIVE, REFUSE_PERFORMATIVE
from simfleet.transport import MIN_AUTONOMY
from simfleet.utils import StrategyBehaviour, TRANSPORT_WAITING, TRANSPORT_IN_CUSTOMER_PLACE, \
    TRANSPORT_MOVING_TO_DESTINATION, TRANSPORT_IN_STATION_PLACE, TRANSPORT_CHARGING, TRANSPORT_NEEDS_CHARGING, \
    CUSTOMER_IN_DEST, chunk_path, request_path, CUSTOMER_LOCATION, TRANSPORT_MOVING_TO_STATION, \
    TRANSPORT_MOVING_TO_CUSTOMER

ONESECOND_IN_MS = 1000


class TransportAgent(Agent):
    """
    Defines the Transport Agent attributes.
    Contains basic methods for agent setup and configuration.
    The methods related to stations might not be necessary. By now we leave
    them to avoid execution problems.
    """

    def __init__(self, agentjid, password):
        super().__init__(agentjid, password)

        self.fleetmanager_id = None
        self.route_id = None
        self.strategy = None
        self.running_strategy = False

        self.__observers = defaultdict(list)
        self.agent_id = None
        self.status = TRANSPORT_WAITING
        self.icon = None
        self.set("current_pos", None)
        self.dest = None
        self.set("path", None)
        self.chunked_path = None
        self.set("speed_in_kmh", 3000)
        self.animation_speed = ONESECOND_IN_MS
        self.distances = []
        self.durations = []
        self.port = None
        self.set("current_customer", None)
        self.current_customer_orig = None
        self.current_customer_dest = None
        self.set("customer_in_transport", None)
        self.num_assignments = 0
        self.stopped = False
        self.ready = False
        self.registration = False
        self.is_launched = False

        self.directory_id = None
        self.fleet_type = None

        # waiting time statistics
        self.waiting_in_queue_time = None
        self.charge_time = None
        self.total_waiting_time = None

        # ATRIBUTES FOR EVENT AND CALLBACK MANAGEMENT
        # Customer in transport event. Triggered when the customer
        # is not in the transport anymore.
        self.customer_in_transport_event = asyncio.Event(loop=self.loop)

        def customer_in_transport_callback(old, new):
            # if event flag is False and new is None
            if not self.customer_in_transport_event.is_set() and new is None:
                # Sets event flag to True, all coroutines waiting for it are awakened
                self.customer_in_transport_event.set()

        self.customer_in_transport_callback = customer_in_transport_callback

    async def setup(self):
        self.set_type("transport")
        self.set_status()
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

    def set(self, key, value):
        old = self.get(key)
        super().set(key, value)
        if key in self.__observers:
            for callback in self.__observers[key]:
                callback(old, value)

    def sleep(self, seconds):
        # await asyncio.sleep(seconds)
        time.sleep(seconds)

    def set_registration(self, status, content=None):
        """
        Sets the status of registration
        Args:
            status (boolean): True if the transport agent has registered or False if not
            content (dict):
        """
        if content is not None:
            self.icon = content["icon"] if self.icon is None else self.icon
            self.fleet_type = content["fleet_type"]
        self.registration = status

    def set_directory(self, directory_id):
        """
        Sets the directory JID address
        Args:
            directory_id (str): the DirectoryAgent jid

        """
        self.directory_id = directory_id

    def set_type(self, transport_type): # new
        self.transport_type = transport_type

    def set_status(self, state=TRANSPORT_WAITING):  #new
        self.status = state

    def watch_value(self, key, callback):
        """
        Registers an observer callback to be run when a value is changed

        Args:
            key (str): the name of the value
            callback (function): a function to be called when the value changes. It receives two arguments: the old and the new value.
        """
        self.__observers[key].append(callback)

    def run_strategy(self):
        """
        Sets the strategy for the transport agent.

        Args:
            strategy_class (``TransportStrategyBehaviour``): The class to be used. Must inherit from ``TransportStrategyBehaviour``
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

    def set_fleetmanager(self, fleetmanager_id):
        """
        Sets the fleetmanager JID address
        Args:
            fleetmanager_id (str): the fleetmanager jid

        """
        logger.info("Setting fleet {} for agent {}".format(fleetmanager_id.split("@")[0], self.name))
        self.fleetmanager_id = fleetmanager_id

    def set_fleet_type(self, fleet_type):
        self.fleet_type = fleet_type

    def set_route_agent(self, route_id):
        """
        Sets the route agent JID address
        Args:
            route_id (str): the route agent jid

        """
        self.route_id = route_id

    async def send(self, msg):
        if not msg.sender:
            msg.sender = str(self.jid)
            logger.debug(f"Adding agent's jid as sender to message: {msg}")
        aioxmpp_msg = msg.prepare()
        await self.client.send(aioxmpp_msg)
        msg.sent = True
        self.traces.append(msg, category=str(self))

    def is_customer_in_transport(self):
        return self.get("customer_in_transport") is not None

    def is_free(self):
        return self.get("current_customer") is None

    async def arrived_to_destination(self):
        """
        Informs that the transport has arrived to its destination.
        It recomputes the new destination and path if picking up a customer
        or drops it and goes to WAITING status again.
        """
        # CHECK IF IT NEEDS MODIFICATION
        self.set("path", None)
        self.chunked_path = None
        # if the transport is going to pick up the customer
        if not self.is_customer_in_transport():  # self.status == TRANSPORT_MOVING_TO_CUSTOMER:
            try:
                # try to pick up the customer and move towards its destination
                self.set("customer_in_transport", self.get("current_customer"))
                await self.move_to(self.current_customer_dest)
            except PathRequestException:
                # if there is no path to customer's destination, cancel it
                await self.cancel_customer()
                self.status = TRANSPORT_WAITING
            except AlreadyInDestination:
                # if the transport is already in the customer's destination, drop the customer off
                logger.error("++++++++++ transport {} is already in customers destination {}".format(self.name, self.current_customer_dest))
                await self.drop_customer()
            else:
                # if there is no error moving to the destination,
                # inform the customer that it has been picked up
                await self.inform_customer(TRANSPORT_IN_CUSTOMER_PLACE)
                self.status = TRANSPORT_MOVING_TO_DESTINATION
                logger.info("Transport {} has picked up the customer {}.".format(self.agent_id,
                                                                                 self.get("current_customer")))
        # if the transport is going towards the destination
        else:  # elif self.status == TRANSPORT_MOVING_TO_DESTINATION:
            await self.drop_customer()

    async def arrived_to_station(self, station_id=None):
        """
        Informs that the transport has arrived to its destination.
        It recomputes the new destination and path if picking up a customer
        or drops it and goes to WAITING status again.
        """
        # self.status = TRANSPORT_IN_STATION_PLACE new

        # ask for a place to charge
        logger.info("Transport {} arrived to station {} and its waiting to charge".format(self.agent_id,
                                                                                          self.get("current_station")))
        self.set("in_station_place", True)  # new

    async def request_access_station(self):

        reply = Message()
        reply.to = self.get("current_station")
        reply.set_metadata("protocol", REQUEST_PROTOCOL)
        reply.set_metadata("performative", ACCEPT_PERFORMATIVE)
        logger.debug("{} requesting access to {}".format(self.name, self.get("current_station"), reply.body))
        await self.send(reply)

        # time waiting in station queue update
        self.waiting_in_queue_time = time.time()

        # WAIT FOR EXPLICIT CONFIRMATION THAT IT CAN CHARGE
        # while True:
        #     msg = await self.receive(timeout=5)
        #     if msg:
        #         performative = msg.get_metadata("performative")
        #         if performative == ACCEPT_PERFORMATIVE:
        #             await self.begin_charging()

    async def begin_charging(self):

        # trigger charging
        self.set("path", None)
        self.chunked_path = None

        data = {
            "status": TRANSPORT_IN_STATION_PLACE,
            "need": self.max_autonomy_km - self.current_autonomy_km
        }
        logger.debug("Transport {} with autonomy {} tells {} that it needs to charge "
                     "{} km/autonomy".format(self.agent_id, self.current_autonomy_km, self.get("current_station"),
                                             self.max_autonomy_km - self.current_autonomy_km))
        await self.inform_station(data)
        self.status = TRANSPORT_CHARGING
        logger.info("Transport {} has started charging in the station {}.".format(self.agent_id,
                                                                                  self.get("current_station")))

        # time waiting in station queue update
        self.charge_time = time.time()
        elapsed_time = self.charge_time - self.waiting_in_queue_time
        if elapsed_time > 0.1:
            self.total_waiting_time += elapsed_time

    def needs_charging(self):
        return (self.status == TRANSPORT_NEEDS_CHARGING) or \
               (self.get_autonomy() <= MIN_AUTONOMY and self.status in [TRANSPORT_WAITING])

    def transport_charged(self):
        self.current_autonomy_km = self.max_autonomy_km

    async def drop_customer(self):
        """
        Drops the customer that the transport is carring in the current location.
        """
        await self.inform_customer(CUSTOMER_IN_DEST)
        self.status = TRANSPORT_WAITING
        logger.info("Transport {} has dropped the customer {} in destination.".format(self.agent_id,
                                                                                       self.get("current_customer")))
        self.set("current_customer", None)
        self.set("customer_in_transport", None)

    async def drop_station(self):
        """
        Drops the customer that the transport is carring in the current location.
        """
        # data = {"status": TRANSPORT_LOADED}
        # await self.inform_station(data)
        self.status = TRANSPORT_WAITING
        logger.debug("Transport {} has dropped the station {}.".format(self.agent_id,
                                                                       self.get("current_station")))
        self.set("current_station", None)

    async def move_to(self, dest):
        """
        Moves the transport to a new destination.

        Args:
            dest (list): the coordinates of the new destination (in lon, lat format)

        Raises:
             AlreadyInDestination: if the transport is already in the destination coordinates.
        """
        if self.get("current_pos") == dest:
            raise AlreadyInDestination
        counter = 5
        path = None
        distance, duration = 0, 0
        while counter > 0 and path is None:
            logger.debug("Requesting path from {} to {}".format(self.get("current_pos"), dest))
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

    async def inform_station(self, data=None):
        """
        Sends a message to the current assigned customer to inform her about a new status.

        Args:
            status (int): The new status code
            data (dict, optional): complementary info about the status
        """
        if data is None:
            data = {}
        msg = Message()
        msg.to = self.get("current_station")
        msg.set_metadata("protocol", TRAVEL_PROTOCOL)
        msg.set_metadata("performative", INFORM_PERFORMATIVE)
        msg.body = json.dumps(data)
        await self.send(msg)

    async def inform_customer(self, status, data=None):
        """
        Sends a message to the current assigned customer to inform her about a new status.

        Args:
            status (int): The new status code
            data (dict, optional): complementary info about the status
        """
        if data is None:
            data = {}
        msg = Message()
        msg.to = self.get("current_customer")
        msg.set_metadata("protocol", TRAVEL_PROTOCOL)
        msg.set_metadata("performative", INFORM_PERFORMATIVE)
        data["status"] = status
        msg.body = json.dumps(data)
        await self.send(msg)

    async def cancel_customer(self, data=None):
        """
        Sends a message to the current assigned customer to cancel the assignment.

        Args:
            data (dict, optional): Complementary info about the cancellation
        """
        logger.error("Transport {} could not get a path to customer {}.".format(self.agent_id,
                                                                                self.get("current_customer")))
        if data is None:
            data = {}
        reply = Message()
        reply.to = self.get("current_customer")
        reply.set_metadata("protocol", REQUEST_PROTOCOL)
        reply.set_metadata("performative", CANCEL_PERFORMATIVE)
        reply.body = json.dumps(data)
        logger.debug("Transport {} sent cancel proposal to customer {}".format(self.agent_id,
                                                                               self.get("current_customer")))
        await self.send(reply)

    async def request_path(self, origin, destination):
        """
        Requests a path between two points (origin and destination) using the RouteAgent service.

        Args:
            origin (list): the coordinates of the origin of the requested path
            destination (list): the coordinates of the end of the requested path

        Returns:
            list, float, float: A list of points that represent the path from origin to destination, the distance and the estimated duration

        Examples:
            >>> path, distance, duration = await self.request_path(origin=[0,0], destination=[1,1])
            >>> print(path)
            [[0,0], [0,1], [1,1]]
            >>> print(distance)
            2.0
            >>> print(duration)
            3.24
        """
        return await request_path(self, origin, destination, self.route_id)

    def set_initial_position(self, coords):
        self.set("current_pos", coords)

    async def set_position(self, coords=None):
        """
        Sets the position of the transport. If no position is provided it is located in a random position.

        Args:
            coords (list): a list coordinates (longitude and latitude)
        """
        if coords:
            self.set("current_pos", coords)
        else:
            self.set("current_pos", random_position())

        logger.debug("Transport {} position is {}".format(self.agent_id, self.get("current_pos")))
        # if the transport has the customer inside and its moving to its destination
        if self.status == TRANSPORT_MOVING_TO_DESTINATION:
            # tell the customer to update its position
            await self.inform_customer(CUSTOMER_LOCATION, {"location": self.get("current_pos")})
        # if the transport has arrived to its self.dest position
        if self.is_in_destination():
            logger.info("Transport {} has arrived to destination. Status: {}".format(self.agent_id, self.status))
            if self.status == TRANSPORT_MOVING_TO_STATION:
                await self.arrived_to_station()
            else:
                # execute method to decide what to do accordingly
                await self.arrived_to_destination()

    def get_position(self):
        """
        Returns the current position of the customer.

        Returns:
            list: the coordinates of the current position of the customer (lon, lat)
        """
        return self.get("current_pos")

    def set_speed(self, speed_in_kmh):
        """
        Sets the speed of the transport.

        Args:
            speed_in_kmh (float): the speed of the transport in km per hour
        """
        self.set("speed_in_kmh", speed_in_kmh)

    def is_in_destination(self):
        """
        Checks if the transport has arrived to its destination.

        Returns:
            bool: whether the transport is at its destination or not
        """
        return self.dest == self.get_position()

    def set_km_expense(self, expense=0):
        self.current_autonomy_km -= expense

    def set_autonomy(self, autonomy, current_autonomy=None):
        self.max_autonomy_km = autonomy
        self.current_autonomy_km = current_autonomy if current_autonomy is not None else autonomy

    def get_autonomy(self):
        return self.current_autonomy_km

    def calculate_km_expense(self, origin, start, dest=None):
        fir_distance = distance_in_meters(origin, start)
        sec_distance = distance_in_meters(start, dest)
        if dest is None:
            sec_distance = 0
        return (fir_distance + sec_distance) // 1000

    def to_json(self):
        """
        Serializes the main information of a transport agent to a JSON format.
        It includes the id of the agent, its current position, the destination coordinates of the agent,
        the current status, the speed of the transport (in km/h), the path it is following (if any), the customer that it
        has assigned (if any), the number of assignments if has done and the distance that the transport has traveled.

        Returns:
            dict: a JSON doc with the main information of the transport.

            Example::

                {
                    "id": "cphillips",
                    "position": [ 39.461327, -0.361839 ],
                    "dest": [ 39.460599, -0.335041 ],
                    "status": 24,
                    "speed": 1000,
                    "path": [[0,0], [0,1], [1,0], [1,1], ...],
                    "customer": "ghiggins@127.0.0.1",
                    "assignments": 2,
                    "distance": 3481.34
                }
        """
        return {
            "id": self.agent_id,
            "position": [float("{0:.6f}".format(coord)) for coord in self.get("current_pos")],
            "dest": [float("{0:.6f}".format(coord)) for coord in self.dest] if self.dest else None,
            "status": self.status,
            "speed": float("{0:.2f}".format(self.animation_speed)) if self.animation_speed else None,
            "path": self.get("path"),
            "customer": self.get("current_customer").split("@")[0] if self.get("current_customer") else None,
            "assignments": self.num_assignments,
            "distance": "{0:.2f}".format(sum(self.distances)),
            "autonomy": self.current_autonomy_km,
            "max_autonomy": self.max_autonomy_km,
            "service": self.fleet_type,
            "fleet": self.fleetmanager_id.split("@")[0],
            "icon": self.icon
        }

    class MovingBehaviour(PeriodicBehaviour):
        """
        This is the internal behaviour that manages the movement of the transport.
        It is triggered when the transport has a new destination and the periodic tick
        is recomputed at every step to show a fine animation.
        This moving behaviour includes to update the transport coordinates as it
        moves along the path at the specified speed.
        """

        async def run(self):
            await self.agent.step()
            self.period = self.agent.animation_speed / ONESECOND_IN_MS
            if self.agent.is_in_destination():
                self.agent.remove_behaviour(self)


class RegistrationBehaviour(CyclicBehaviour):
    async def on_start(self):
        logger.debug("Strategy {} started in directory".format(type(self).__name__))

    def set_registration(self, decision):
        self.agent.registration = decision

    async def send_registration(self):
        """
        Send a ``spade.message.Message`` with a proposal to directory to register.
        """
        logger.debug(
            "Transport {} sent proposal to register to directory {}".format(self.agent.name, self.agent.directory_id))
        content = {
            "jid": str(self.agent.jid),
            "type": self.agent.transport_type,
            "status": self.agent.status,
            "position": self.agent.get_position(),
        }
        msg = Message()
        msg.to = str(self.agent.directory_id)
        msg.set_metadata("protocol", REGISTER_PROTOCOL)
        msg.set_metadata("performative", REQUEST_PERFORMATIVE)
        msg.body = json.dumps(content)
        await self.send(msg)

    async def run(self):
        try:
            if not self.agent.registration:
                await self.send_registration()
            msg = await self.receive(timeout=10)
            if msg:
                performative = msg.get_metadata("performative")
                if performative == ACCEPT_PERFORMATIVE:
                    self.set_registration(True)
                    logger.debug("Registration in the directory")
        except CancelledError:
            logger.debug("Cancelling async tasks...")
        except Exception as e:
            logger.error("EXCEPTION in RegisterBehaviour of Station {}: {}".format(self.agent.name, e))


class RegistrationBehaviourOld(CyclicBehaviour):
    async def on_start(self):
        logger.debug("Strategy {} started in transport".format(type(self).__name__))

    async def send_registration(self):
        """
        Send a ``spade.message.Message`` with a proposal to manager to register.
        """
        logger.debug(
            "Transport {} sent proposal to register to manager {}".format(self.agent.name, self.agent.fleetmanager_id))
        content = {
            "name": self.agent.name,
            "jid": str(self.agent.jid),
            "fleet_type": self.agent.fleet_type
        }
        msg = Message()
        msg.to = str(self.agent.fleetmanager_id)
        msg.set_metadata("protocol", REGISTER_PROTOCOL)
        msg.set_metadata("performative", REQUEST_PERFORMATIVE)
        msg.body = json.dumps(content)
        await self.send(msg)

    async def run(self):
        try:
            if not self.agent.registration:
                await self.send_registration()
            msg = await self.receive(timeout=10)
            if msg:
                performative = msg.get_metadata("performative")
                if performative == ACCEPT_PERFORMATIVE:
                    content = json.loads(msg.body)
                    self.agent.set_registration(True, content)
                    logger.info("[{}] Registration in the fleet manager accepted: {}.".format(self.agent.name,
                                                                                              self.agent.fleetmanager_id))
                    self.kill(exit_code="Fleet Registration Accepted")
                elif performative == REFUSE_PERFORMATIVE:
                    logger.warning("Registration in the fleet manager was rejected (check fleet type).")
                    self.kill(exit_code="Fleet Registration Rejected")
        except CancelledError:
            logger.debug("Cancelling async tasks...")
        except Exception as e:
            logger.error("EXCEPTION in RegisterBehaviour of Transport {}: {}".format(self.agent.name, e))


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

    async def pick_up_customer(self, customer_id, origin, dest):
        """
        Starts a TRAVEL_PROTOCOL to pick up a customer and get him to his destination.
        It automatically launches all the travelling process until the customer is
        delivered. This travelling process includes to update the transport coordinates as it
        moves along the path at the specified speed.

        Args:
            customer_id (str): the id of the customer
            origin (list): the coordinates of the current location of the customer
            dest (list): the coordinates of the target destination of the customer
        """
        # FOR THE CAR SHARING SYSTEM, WE WILL USE THIS METHOD ONCE THE CUSTOMER
        # INFORMS THE TRANSPORT THAT IS HAS ARRIVED TO ITS POSITION. IN THAT WAY
        # WE MAKE USE OF THE ORIGINAL IMPLEMENTATIONS.

        # THE CALL SHOULD TRIGGER IMMEDIATELY THE AlreadyInDestination event
        # THE TRANSPORT SHOULD THEN PICK UP THE CUSTOMER AND MOVE TO ITS DESTINATION

        logger.info("Transport {} on route to customer {}".format(self.agent.name, customer_id))
        reply = Message()
        reply.to = customer_id
        reply.set_metadata("performative", INFORM_PERFORMATIVE)
        reply.set_metadata("protocol", TRAVEL_PROTOCOL)
        content = {
            "status": TRANSPORT_MOVING_TO_CUSTOMER
        }
        reply.body = json.dumps(content)
        self.set("current_customer", customer_id)
        self.agent.current_customer_orig = origin
        self.agent.current_customer_dest = dest
        await self.send(reply)
        self.agent.num_assignments += 1
        try:
            await self.agent.move_to(self.agent.current_customer_orig)
        except AlreadyInDestination:
            await self.agent.arrived_to_destination()

    async def accept_customer(self, customer_id):
        """
        Sends a ``spade.message.Message`` to a customer to accept a booking.
        It uses the REQUEST_PROTOCOL and the ACCEPT_PERFORMATIVE.

        Args:
            customer_id (str): The Agent JID of the transport
        """
        # COPIED FROM customer.py AND MODIFIED, MIGHT REQUIRE FURTHER MODIFICATION
        reply = Message()
        reply.to = str(customer_id)
        reply.set_metadata("protocol", REQUEST_PROTOCOL)
        reply.set_metadata("performative", ACCEPT_PERFORMATIVE)
        content = {
            "transport_id": str(self.agent.jid),
            "position": self.agent.get("current_pos")
        }
        reply.body = json.dumps(content)
        await self.send(reply)
        self.agent.set("current_costumer", customer_id)
        logger.info("Transport {} accepted booking from customer {}".format(self.agent.name, customer_id))

    async def refuse_customer(self, customer_id):
        """
        Sends an ``spade.message.Message`` to a customer to refuse a booking.
        It uses the REQUEST_PROTOCOL and the REFUSE_PERFORMATIVE.

        Args:
            customer_id (str): The Agent JID of the transport
        """
        # COPIED FROM customer.py AND MODIFIED, MIGHT REQUIRE FURTHER MODIFICATION
        reply = Message()
        reply.to = str(customer_id)
        reply.set_metadata("protocol", REQUEST_PROTOCOL)
        reply.set_metadata("performative", REFUSE_PERFORMATIVE)
        content = {
            "transport_id": str(self.agent.jid),
            "position": self.agent.get("current_pos")
        }
        reply.body = json.dumps(content)

        await self.send(reply)
        logger.info("Transport {} refused booking from customer {}".format(self.agent.name,
                                                                           customer_id))

    async def deassign_customer(self):
        """
        Triggered when, by any reason, a customer cancels their already accepted booking
        """
        # Delete saved values (destination, etc.) belonging to booked customer
        self.agent.set("current_customer", None)
        self.agent.current_customer_orig = None
        self.agent.current_customer_dest = None

    async def run(self):
        raise NotImplementedError
