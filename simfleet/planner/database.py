import copy
import json
import math

import numpy as np
from geopy.distance import geodesic
from loguru import logger

from simfleet.planner.constants import CONFIG_FILE, ACTIONS_FILE, ROUTES_FILE, SPEED, PRINT_OUTPUT, RELOAD_ACTIONS, \
    DEEPCOPY
from simfleet.planner.generators_utils import has_enough_autonomy

VERBOSE = 0
FILTERED_STATIONS_LOGGER = 0


class Database:
    def __init__(self):
        # this parameter is to print the average value of reachable stations at the end of the BRPS process
        self.reachable_stations = []
        try:
            f2 = open(CONFIG_FILE, "r")
            self.config_dic = json.load(f2)

            f2 = open(ACTIONS_FILE, "r")
            self.actions_dic = json.load(f2)

            f2 = open(ROUTES_FILE, "r")
            self.routes_dic = json.load(f2)

        except Exception as e:
            print(str(e))
            exit()

        self.agents = None
        self.joint_plan = {}
        self.list_of_plans = {}
        self.best_prev_plan = {}
        self.optimal_orders = {}

        self.create_agents()

    def reload_actions(self):
        f2 = open(ACTIONS_FILE, "r")
        self.actions_dic = json.load(f2)

    def get_route(self, p1, p2):
        key = str(p1) + ":" + str(p2)
        route = self.routes_dic.get(key)
        if route is None:
            # En el futur, demanar la ruta al OSRM
            logger.critical(f"ERROR :: There is no route for key {key} in the routes_dic")
            exit()
        return route

    # Creates Transport Agents that will act as players in the Best Response game
    def create_agents(self):
        agents = []
        for agent in self.config_dic.get('transports'):
            agent_id = agent.get('name')
            agent_dic = {
                'id': agent_id,
                'initial_position': agent.get('position'),
                'max_autonomy': agent.get('autonomy'),
                'current_autonomy': agent.get('current_autonomy')
            }
            agents.append(agent_dic)
            self.list_of_plans[agent_id] = []
            self.best_prev_plan[agent_id] = (0, None)
            self.optimal_orders[agent_id] = {}

        self.agents = agents
        self.assign_goals()

    def assign_goals(self):
        # List with all customers
        customer_dics = self.config_dic.get('customers')
        customers = []
        for customer in customer_dics:
            customers.append(customer.get('name'))

        # Number of customers each agent will initially pick up
        customers_per_agent = math.ceil(len(customers) / len(self.agents))

        for agent in self.agents:

            if len(customers) >= customers_per_agent:
                # Assign their customers
                # goals = random.sample(customers, k=customers_per_agent)
                # TODO hardcoded to repartir 1 2 3
                goals = customers[0:customers_per_agent]
                customers = [c for c in customers if c not in goals]
            else:
                goals = copy.deepcopy(customers)  # customers.copy()

            agent['goals'] = goals
            if PRINT_OUTPUT > 0:
                logger.info(f"Goals for agent {agent.get('id')}: {goals}")

    def get_customer_origin(self, customer_id):
        for customer in self.config_dic.get('customers'):
            if customer.get('name') == customer_id:
                return customer.get('position')

    #############################################################
    ##################### STATION FUNCTIONS #####################
    #############################################################
    def get_station_places(self, station_name):
        for station in self.config_dic.get('stations'):
            if station.get('name') == station_name:
                return station.get("places")

    def check_simultaneous_charge(self, agent, station, at_station):
        for usage in self.joint_plan.get('station_usage').get(station):
            if usage.get('agent') != agent and usage.get('inv') != 'INV':
                if usage.get('at_station') == at_station:
                    if PRINT_OUTPUT > 0:
                        logger.warning(f"Found simultaneous charge among agents {usage.get('agent')} and {agent}")
                    return True
        return False

    def check_available_poles(self, agent, station, at_station):
        c = 0
        # DEFINIR QUE FER PER A QUAN DOS AGENTS ARRIBEN A LA VEGADA
        for usage in self.joint_plan.get('station_usage').get(station):
            if usage.get('agent') != agent and usage.get('inv') != 'INV':
                # A place is occupied when the agent arrives at the station (at_station time) if there are agents
                # that have started charging before the agent arrived and will finish after the agent arrived
                if usage.get('init_charge') < at_station < usage.get('end_charge'):
                    c += 1

        return self.get_station_places(station) - c

    # Returns list of agents who are charging or will charge before the current agent does and a boolean indicating
    # if the agents in that list is higher than the number of places in the station. If so, there is a queue.
    def check_station_queue(self, agent, station, at_station):
        # DEFINIR QUE FER PER A QUAN DOS AGENTS ARRIBEN A LA VEGADA
        queue = []
        # Get agents that arrived to the station before at_station time, and will finish charging after at_station time
        for usage in self.joint_plan.get('station_usage').get(station):
            if usage.get('agent') != agent and usage.get('inv') != 'INV':
                if usage.get('at_station') < at_station < usage.get('end_charge'):
                    queue.append(usage)

        queue.sort(key=lambda x: x.get('at_station'))

        return queue, len(queue) > self.get_station_places(station)

    def filter_station_actions_old(self, agent_id, agent_pos, agent_autonomy):

        if RELOAD_ACTIONS:
            self.reload_actions()
        agent_actions = self.actions_dic.get(agent_id)

        move_to_station_actions = agent_actions.get("MOVE-TO-STATION")
        charge_actions = agent_actions.get("CHARGE")

        # max_dist = MAX_STATION_DIST

        filtered_move_actions = []
        filtered_stations = []

        for a in move_to_station_actions:
            route = self.get_route(agent_pos, a.get('attributes').get('station_position'))
            if has_enough_autonomy(agent_autonomy, route.get('distance')):
                filtered_move_actions.append(copy.deepcopy(a))  # a.copy())
                filtered_stations.append(a.get('attributes').get('station_id'))
            # max_dist += 250

        filtered_charge_actions = [a for a in charge_actions if
                                   a.get('attributes').get('station_id') in filtered_stations]

        # logger.info(f" ")
        # logger.info(f"{len(filtered_stations)} reachable stations")
        return filtered_move_actions, filtered_charge_actions

    def filter_station_actions(self, agent_id, agent_pos, agent_autonomy, non_served_customers):

        if RELOAD_ACTIONS:
            self.reload_actions()
        agent_actions = self.actions_dic.get(agent_id)

        move_to_station_actions = agent_actions.get("MOVE-TO-STATION")
        charge_actions = agent_actions.get("CHARGE")

        # max_dist = MAX_STATION_DIST

        filtered_move_actions = []
        filtered_stations = []

        # # find furthest customer among non_served
        # max_dist = -1
        # for customer in non_served_customers:
        #     origin = self.get_customer_origin(customer)
        #     route = self.get_route(agent_pos, origin)
        #     if route.get('distance') > max_dist:
        #         max_dist = route.get('distance')
        # max_dist = math.inf
        # logger.info(f" ")
        # logger.warning(f"Autonomy is {agent_autonomy}km")
        # logger.warning(f"Max customer dist is {max_dist}m")

        # assign to each customer its own distance
        customer_dists = {}
        for customer in non_served_customers:
            origin = self.get_customer_origin(customer)
            route = self.get_route(agent_pos, origin)
            customer_dists[customer] = route.get('distance')

        for a in move_to_station_actions:
            # Station attributes
            station_id = a.get('attributes').get('station_id')
            station_position = a.get('attributes').get('station_position')

            route = self.get_route(agent_pos, station_position)
            # Check if station is reachable
            if has_enough_autonomy(agent_autonomy, route.get('distance')):
                # Check if it is close to any of the non served customers
                for customer in non_served_customers:
                    # route = self.get_route(self.get_customer_origin(customer), station_position)
                    # if route.get('distance') <= RADIUS:
                    distance = geodesic(self.get_customer_origin(customer), station_position).meters
                    # if distance <= max_dist:
                    if distance <= customer_dists.get(customer):
                        filtered_move_actions.append(copy.deepcopy(a))  # a.copy())
                        filtered_stations.append(station_id)
                        break
                    else:
                        if FILTERED_STATIONS_LOGGER > 0:
                            logger.warning(
                                f"Agent {agent_id} CAN reach station {station_id} which is {route.get('distance')}m away with autonomy of {agent_autonomy}. "
                                f"However it is not close enough to customer {customer}.")
                            logger.warning(
                                f"Customer distance: {customer_dists.get(customer)}, station distance to customer {distance}")
            else:
                if FILTERED_STATIONS_LOGGER > 0:
                    logger.warning(
                        f"Agent {agent_id} can't reach station {station_id} which is {route.get('distance')}m away with autonomy of {agent_autonomy}")

        # If after the process there are no stations in filtered_stations, repeat without customer restrictions
        if len(filtered_stations) == 0:
            for a in move_to_station_actions:
                # Station attributes
                station_id = a.get('attributes').get('station_id')
                station_position = a.get('attributes').get('station_position')

                route = self.get_route(agent_pos, station_position)
                # Check if station is reachable
                if has_enough_autonomy(agent_autonomy, route.get('distance')):
                    filtered_move_actions.append(copy.deepcopy(a))
                    filtered_stations.append(station_id)
                else:
                    if FILTERED_STATIONS_LOGGER > 0:
                        logger.warning(
                            f"Agent {agent_id} can't reach station {station_id} which is {route.get('distance')}m away with autonomy of {agent_autonomy}")

        filtered_charge_actions = [a for a in charge_actions if
                                   a.get('attributes').get('station_id') in filtered_stations]

        if FILTERED_STATIONS_LOGGER > 0: logger.info(f"{len(filtered_stations)} reachable stations")
        self.reachable_stations.append(len(filtered_stations))
        return filtered_move_actions, filtered_charge_actions

    #############################################################
    ##################### PLANNING FUNCTIONS ####################
    #############################################################
    def meters_to_seconds(self, distance_in_meters):
        # km/h to m/s
        speed = SPEED / 3.6
        t = distance_in_meters / speed
        return t

    # Given two lists of actions, returns the pick_up / move-to-dest tuple for the same customer
    # TODO modify for fixed goals
    def get_customer_couples(self, pick_up_actions, move_to_dest_actions):
        res = []
        for a in pick_up_actions[:]:
            customer_id = a.get('attributes').get('customer_id')
            for b in move_to_dest_actions[:]:
                if b.get('attributes').get('customer_id') == customer_id:
                    if DEEPCOPY:
                        res.append((copy.deepcopy(a), copy.deepcopy(b)))
                    else:
                        res.append((a, b))
        return res

    def get_customer_couple(self, agent, customer_id):
        agent_actions = self.actions_dic.get(agent)
        pick_up_actions = agent_actions.get("PICK-UP")
        move_to_dest_actions = agent_actions.get("MOVE-TO-DEST")

        for action in pick_up_actions:
            if action.get('attributes').get('customer_id') == customer_id:
                action1 = action
                break
        for action in move_to_dest_actions:
            if action.get('attributes').get('customer_id') == customer_id:
                action2 = action
                break
        if DEEPCOPY:
            return copy.deepcopy(action1), copy.deepcopy(action2)
        else:
            return action1, action2

    def get_customer_couple2(self, agent, customer_id):
        agent_actions = [a for a in self.actions_dic if a.get('agent') == agent]
        pick_up_actions = [a for a in agent_actions if a.get('type') == 'PICK-UP']
        move_to_dest_actions = [a for a in agent_actions if a.get('type') == 'MOVE-TO-DEST']
        action1 = [a for a in pick_up_actions if a.get('attributes').get('customer_id') == customer_id]
        action2 = [a for a in move_to_dest_actions if a.get('attributes').get('customer_id') == customer_id]

        return action1[0], action2[0]

    # Given two lists of actions, returns the move-to-station / charge tuple for the same station
    # TODO modify for only n closer stations
    def get_station_couples(self, move_to_station_actions, charge_actions):
        res = []
        for a in move_to_station_actions:
            station_id = a.get('attributes').get('station_id')
            for b in charge_actions:
                if b.get('attributes').get('station_id') == station_id:
                    if DEEPCOPY:
                        res.append((copy.deepcopy(a), copy.deepcopy(b)))
                    else:
                        res.append((a, b))
        return res

    def extract_route(self, action):
        origin = action.get('statistics').get('movement_start')
        if action.get('type') == 'PICK-UP':
            destination = action.get('attributes').get('customer_origin')
        elif action.get('type') == 'MOVE-TO-DEST':
            destination = action.get('attributes').get('customer_dest')
        else:
            destination = action.get('attributes').get('station_position')

        return self.get_route(origin, destination)

    def fill_statistics(self, action, current_pos=None, current_autonomy=None, agent_max_autonomy=None,
                        current_time=None):
        if action.get('type') == 'PICK-UP':
            # distance from transport position to customer origin
            p1 = current_pos
            p2 = action.get('attributes').get('customer_origin')
            route = self.get_route(p1, p2)
            dist = route.get('distance')
            time = self.meters_to_seconds(dist)
            action['statistics']['dist'] = dist
            action['statistics']['time'] = time
            action['statistics']['init'] = current_time
            action['statistics']['movement_start'] = p1

        elif action.get('type') == 'MOVE-TO-DEST':
            # distance from customer_origin to customer_destination
            p1 = action.get('attributes').get('customer_origin')
            p2 = action.get('attributes').get('customer_dest')
            route = self.get_route(p1, p2)
            dist = route.get('distance')
            time = self.meters_to_seconds(dist)
            action['statistics']['dist'] = dist
            action['statistics']['time'] = time
            action['statistics']['init'] = current_time
            action['statistics']['movement_start'] = p1

        elif action.get('type') == 'MOVE-TO-STATION':
            # distance from transport position to station position
            p1 = current_pos
            p2 = action.get('attributes').get('station_position')
            # logger.debug(f"Station {action.get('attributes').get('station_id')} in position {p2}")
            route = self.get_route(p1, p2)
            dist = route.get('distance')
            time = self.meters_to_seconds(dist)
            action['statistics']['dist'] = dist
            action['statistics']['time'] = time
            action['statistics']['init'] = current_time
            action['statistics']['movement_start'] = p1

        elif action.get('type') == 'CHARGE':

            # Get variables
            agent = action.get('agent')
            station = action.get('attributes').get('station_id')

            # 1. Compute charging time. The charge action will finish at the end of the charging time if there are
            # free places at the station
            need = agent_max_autonomy - current_autonomy
            charging_time = need / action.get('attributes').get('power')

            # Nou check per veure si hi ha algú que està arribant exactament a la vegada que jo; si això passara,
            # m'incremente el meu temps d'arribada, recalcule els meus temps i torne a fer les comprovacions
            if self.check_simultaneous_charge(agent, station, current_time):
                current_time += 0.001

            # 2. Check if there will be a free place to charge at the arrival to the station
            available_poles = self.check_available_poles(agent, station, current_time)
            if VERBOSE > 0:
                logger.info(
                    f"Evaluating charge action of agent {agent} in station {station} at time {current_time:.4f}")
                logger.info(f"There are {available_poles} available poles")
            #   2.2 If there is not, compute waiting time, add it to charging time to compute total time
            if available_poles == 0:
                queue, check = self.check_station_queue(agent, station, current_time)
                # FOR ERROR DEBUGGING
                if len(queue) == 0:
                    for station in self.joint_plan.get('station_usage').keys():
                        if len(self.joint_plan.get('station_usage').get(station)) == 0:
                            logger.debug(f"{station:20s} : []")
                        else:
                            logger.debug(f"{station:20s} : [")
                            for usage in self.joint_plan.get('station_usage').get(station):
                                logger.debug(f"\t{usage.get('agent'):10s}, {usage.get('at_station'):.4f}, "
                                             f"{usage.get('init_charge'):.4f}, {usage.get('end_charge'):.4f}, "
                                             f"{usage.get('inv')}")
                            logger.debug("] \n")
                if VERBOSE > 0:
                    logger.info(f"There are {len(queue)} agents in front of {agent}")
                # Get que last X agents of the queue which are in front of you, where X is the number of poles
                # if check, there are more agents in front of me than places in the station
                if check:
                    # keep only last X to arrive
                    queue = queue[-self.get_station_places(station):]
                # if not check, there are as many agents in front of me as places in the station
                end_times = [x.get('end_charge') for x in queue]
                # FOR ERROR DEBUGGING
                try:
                    # Get charge init time
                    init_charge = min(end_times)
                except ValueError:
                    logger.error(f"Queue: {queue}")
                    logger.error(f"Check: {check}")
                    logger.error(f"end_times: {end_times}")
                    self.print_joint_plan()
                # end_charge = init_charge + charging_time
                # Compute waiting time
                waiting_time = init_charge - current_time
                if VERBOSE > 0:
                    logger.info(
                        f"Agent {agent} will begin charging at time {init_charge:.4f} after waiting {waiting_time:.4f} seconds")
            elif available_poles < 0:
                logger.critical(
                    f"Error computing available poles for station {station}: {available_poles} at time {current_time}")
                logger.debug("\n")
                logger.debug("Station usage:")
                for station in self.joint_plan.get('station_usage').keys():
                    if len(self.joint_plan.get('station_usage').get(station)) == 0:
                        logger.debug(f"{station:20s} : []")
                    else:
                        logger.debug(f"{station:20s} : [")
                        for usage in self.joint_plan.get('station_usage').get(station):
                            logger.debug(f"\t{usage.get('agent'):10s}, {usage.get('at_station'):.4f}, "
                                         f"{usage.get('init_charge'):.4f}, {usage.get('end_charge'):.4f}, "
                                         f"{usage.get('inv')}")
                        logger.debug("] \n")
            # if there are available poles
            else:
                init_charge = current_time
                waiting_time = 0
                if VERBOSE > 0:
                    logger.info(f"There are available places")
                    logger.info(
                        f"Agent {agent} will begin charging at time {init_charge:.4f} after waiting {waiting_time:.4f} seconds")
            # FOR ERROR DEBUGGING
            if init_charge < current_time:
                logger.critical("Error computing charge times")
                logger.error(f"Available_poles: {available_poles}")
                logger.error(f"Queue: {queue}")
                logger.error(f"Check: {check}")
                logger.error(f"end_times: {end_times}")
                logger.debug("Station usage:")
                for station in self.joint_plan.get('station_usage').keys():
                    if len(self.joint_plan.get('station_usage').get(station)) == 0:
                        logger.debug(f"{station:20s} : []")
                    else:
                        logger.debug(f"{station:20s} : [")
                        for usage in self.joint_plan.get('station_usage').get(station):
                            logger.debug(f"\t{usage.get('agent'):10s}, {usage.get('at_station'):.4f}, "
                                         f"{usage.get('init_charge'):.4f}, {usage.get('end_charge'):.4f}, "
                                         f"{usage.get('inv')}")
                        logger.debug("] \n")
                exit()

            # Write times
            #   arrival at the station
            action['statistics']['at_station'] = current_time
            #   begin charging
            action['statistics']['init_charge'] = init_charge
            #   total time
            total_time = charging_time + waiting_time
            action['statistics']['time'] = total_time
            # amount (of something) to charge
            action['statistics']['need'] = need

        return action

    #############################################################
    ################## BEST RESPONSE FUNCTIONS ##################
    #############################################################
    def to_string_joint_plan(self):
        res = "\n"
        res += "Individual plans:\n"
        for agent in self.joint_plan.get('individual').keys():
            plan = self.joint_plan.get('individual').get(agent)
            if plan is None:
                res += f"{agent:20s} : NO PLAN\n"
            else:
                if plan.inv is not None:
                    res += f"{agent:20s} : Plan with {len(plan.entries):2d} entries and utility {plan.utility:.4f}"
                    res += plan.to_string_plan() + "\n"
                else:
                    res += f"{agent:20s} : Plan with {len(plan.entries):2d} entries and utility {plan.utility:.4f}"
                    res += plan.to_string_plan() + "\n"

        res += "\n"
        res += "Joint plan:\n"
        res += self.joint_plan.get("joint").print_plan()

        res += "\n"
        res += "Table of goals:\n"
        for customer in self.joint_plan.get('table_of_goals').keys():
            res += f"{customer:20s} : {self.joint_plan.get('table_of_goals').get(customer)}\n"

        res += "\n"
        res += "Station usage:\n"
        for station in self.joint_plan.get('station_usage').keys():
            if len(self.joint_plan.get('station_usage').get(station)) == 0:
                res += f"{station:20s} : []\n"
            else:
                res += f"{station:20s} : [\n"
                for usage in self.joint_plan.get('station_usage').get(station):
                    if usage.get('inv') is None:
                        res += f"\t{usage.get('agent'):10s}, {usage.get('at_station'):.4f}, {usage.get('init_charge'):.4f}, {usage.get('end_charge'):.4f}\n"
                    else:
                        res += f"\t{usage.get('agent'):10s}, {usage.get('at_station'):.4f}, {usage.get('init_charge'):.4f}, {usage.get('end_charge'):.4f}, {usage.get('inv')}\n"
                res += "] \n"

        res += "\n"
        res += "No change in plan:\n"
        for agent in self.joint_plan.get('no_change').keys():
            res += f"{agent:20s} : {self.joint_plan.get('no_change').get(agent)}\n"

        res += "\n"
        res += "Agent utilities:\n"
        utilities = []
        for agent in self.joint_plan.get('individual').keys():
            utilities.append(self.joint_plan.get('individual').get(agent).utility)
            res += f"{agent:20s} : {self.joint_plan.get('individual').get(agent).utility:.4f}\n"

        utilities = np.array(utilities)
        res += "\n"
        res += f"Mean utility: {utilities.mean():.4f}. Std deviation: {utilities.std():.4f}. Median: {np.median(utilities):.4f}.\n"

        res += "#########################################################################\n\n"

        return res
