"""
Develops a plan for a TransportAgent
"""
import heapq
import json
import math
import random
import time

from loguru import logger

from simfleet.planner.constants import SPEED, CONFIG_FILE, \
    ACTIONS_FILE, ROUTES_FILE, HEURISTIC
from simfleet.planner.evaluator import evaluate_node, evaluate_plan
from simfleet.planner.generators_utils import has_enough_autonomy, calculate_km_expense
from simfleet.planner.plan import Plan

VERBOSE = 0  # 2, 1 or 0 according to verbosity level

DEBUG = False

PRINT_GOALS = False
PRINT_PLAN = False
CHARGE_WHEN_NOT_FULL = True


class Node:
    def __init__(self, parent=None):

        # If there is no parent, use default value for attributes
        if parent is None:
            self.parent = None
            # Agent attributes in the node
            #   current position
            self.agent_pos = None
            #   current autonomy
            self.agent_autonomy = None
            # Node planner-related attributes
            self.init_time = 0.0
            self.actions = []

            # Llista customers de l'agent + llista d'atesos
            # New: list with names of customers assigned to the agent
            self.agent_goals = []
            # List with names of already served customers
            self.completed_goals = []

            # Llista customers atesos + Llista de customers per atendre

        # If there is parent, inherit attributes
        else:
            self.parent = parent
            self.agent_pos = parent.agent_pos[:]
            self.agent_autonomy = parent.agent_autonomy  # .copy()
            self.init_time = parent.end_time  # .copy()
            self.actions = parent.actions[:]  # .copy()
            # New
            self.agent_goals = parent.agent_goals[:]  # .copy()
            self.completed_goals = parent.completed_goals[:]  # .copy()

        # Independent values for every node
        #   own f-value
        self.value = None
        self.end_time = None
        # to store children node (if any)
        self.children = []

    def set_end_time(self):
        self.end_time = sum(a.get('statistics').get('time') for a in self.actions)

    # Given the list of completed goals, which contains tuples (customer_id, pick_up_time),
    # compiles a list of the served customers' ids.
    def already_served(self):
        res = []
        for tup in self.completed_goals:
            res.append(tup[0])
        return res

    def print_node(self):
        action_string = "\n"
        for a in self.actions:
            if a.get('type') in ['PICK-UP', 'MOVE-TO-DEST']:
                action_string += str((a.get('agent'), a.get('type'), a.get('attributes').get('customer_id'))) + ",\n"
            else:
                action_string += str((a.get('agent'), a.get('type'), a.get('attributes').get('station_id'))) + ",\n"

            # if its the last action, remove ", "
            if a == self.actions[-1]:
                action_string = action_string[:-2]
        logger.info(
            f'(\n\tagent position:\t{self.agent_pos}\n'
            f'\tagent autonomy:\t{self.agent_autonomy}\n'
            f'\tactions:\t[{action_string}]\n'
            f'\tinit time:\t{self.init_time:.4f}\n'
            f'\tend time:\t{self.end_time:.4f}\n'
            f'\tvalue:\t{self.value:.4f}\n'
            f'\tagent goals:\t{self.agent_goals}\n'
            f'\tcompleted goals:\t{self.completed_goals}\n'
            f'\thas parent?:\t{self.parent is not None}\n'
            f'\thas children?:\t{len(self.children)}\t)'
        )

    def print_node_action_info(self):
        action_string = ""
        for a in self.actions:
            action_string += str(a) + "\n"
        logger.info(
            f'(\n\tagent_position:\t{self.agent_pos}\n'
            f'\tagent_autonomy:\t{self.agent_autonomy}\n'
            f'\tactions:\t[\n{action_string}]\n'
            f'\tinit_time:\t{self.init_time:.4f}\n'
            f'\tend_time:\t{self.end_time:.4f}\n'
            f'\tvalue:\t{self.value:.4f}\n'
            f'\tagent goals:\t{self.agent_goals}\n'
            f'\tcompleted_goals:\t{self.completed_goals}\n'
            f'\thas parent?:\t{self.parent is not None}\n'
            f'\thas children?:\t{len(self.children)}\t)'
        )


def check_tree(leaf_node):
    node = leaf_node
    i = -1
    while node.parent is not None:
        i += 1
        logger.info("-------------------------------------------------------------------")
        logger.info(f"Generation -{i:2d}")
        node.print_node_action_info()
        plan = Plan(node.actions, node.value, node.completed_goals)
        logger.info(plan.to_string_plan())
        logger.info("-------------------------------------------------------------------")

        node = node.parent

    i += 1
    logger.info("-------------------------------------------------------------------")
    logger.info(f"Generation -{i:2d}")
    node.print_node_action_info()
    plan = Plan(node.actions, node.value, node.completed_goals)
    logger.info(plan.to_string_plan())
    logger.info("-------------------------------------------------------------------")


def print_table_of_goals(table_of_goals):
    logger.info("·············································")
    logger.info("| {:<10} {:<30} |".format('Customer', 'Contents'))
    for k, v in table_of_goals.items():
        contents = str(v)
        logger.info("| {:<10} {:<30} |".format(k, contents))
    logger.info("·············································")


def to_string_table_of_goals(table_of_goals):
    s = "\n"
    s += "·············································\n"
    s += "| {:<10} {:<30} |\n".format('Customer', 'Contents')
    for k, v in table_of_goals.items():
        contents = str(v)
        s += "| {:<10} {:<30} |\n".format(k, contents)
    s += "·············································\n"

    return s


class Planner:
    def __init__(self, database, agent_id, agent_pos, agent_max_autonomy, agent_autonomy,
                 agent_goals, previous_plan=None, start_node=None):

        # Precalculated routes and actions
        # self.config_dic = config_dic
        # self.actions_dic = actions_dic
        # self.routes_dic = routes_dic
        self.db = database

        # Transport agent attributes
        self.agent_id = agent_id
        self.agent_pos = agent_pos
        self.agent_max_autonomy = agent_max_autonomy
        self.agent_autonomy = agent_autonomy
        # New
        self.agent_goals = agent_goals

        # Table of goals
        self.table_of_goals = {}
        # Node heap
        self.open_nodes = []

        # Joint plan
        self.joint_plan = self.db.joint_plan
        # if joint_plan is None:
        #     joint_plan = {}
        # self.joint_plan = joint_plan

        # Best solution to prune tree
        self.best_solution = None
        self.best_solution_value = -math.inf
        self.solution_nodes = []
        if previous_plan is not None:
            self.previous_plan = previous_plan
        else:
            self.previous_plan = None
        self.plan = None

        # Variables to activate and deactivate pruning methods
        self.save_partial_solutions = False
        self.best_solution_prune = True
        if not HEURISTIC:
            self.best_solution_prune = False

        # Planner statistics
        self.generated_nodes = 0
        self.max_queue_length = 0

        # Plan from a specific node
        self.start_node = start_node

        self.create_table_of_goals()

    # Reads plan of every agent (joint plan) and fills the corresponding table of goals
    # If the joint plan is empty, creates an entry per customer and initialises its
    # pick-up time to infinity
    def create_table_of_goals(self):
        if len(self.joint_plan) == 0:
            for customer in self.db.config_dic.get("customers"):
                self.table_of_goals[customer.get("name")] = (None, math.inf)
        else:  # extract from joint plan
            for customer in self.joint_plan.get('table_of_goals').keys():
                tup = self.joint_plan.get('table_of_goals').get(customer)
                if tup[0] is None:
                    self.table_of_goals[customer] = (None, math.inf)
                else:
                    self.table_of_goals[customer] = (tup[0], tup[1])
                    # tup[0] transport_agent, tup[1] pick_up_time
        if PRINT_GOALS:
            logger.info(
                f"Initial table of goals: {to_string_table_of_goals(self.table_of_goals)}")  # \n{self.table_of_goals}")
            # print_table_of_goals(self.table_of_goals)

    def get_station_places(self, station_name):
        for station in self.db.config_dic.get('stations'):
            if station.get('name') == station_name:
                return station.get("places")

    def check_simultaneous_charge(self, agent, station, at_station):
        for usage in self.joint_plan.get('station_usage').get(station):
            if usage.get('agent') != agent and usage.get('inv') != 'INV':
                if usage.get('at_station') == at_station:
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

        return self.db.get_station_places(station) - c

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

        return queue, len(queue) > self.db.get_station_places(station)

    # Returns a list with station usages which start before init_time and end after init_time
    def get_usages_interval(self, agent, station, init_time, expected_end_time):
        res = []
        for usage in self.joint_plan.get('station_usage').get(station):
            if usage.get('agent') is not agent:
                # if it starts at the same time as me
                if usage.get('init') == init_time:
                    # if they finish before I do, consider them in front of me
                    if usage.get('end') < expected_end_time:
                        res.append(usage)
                    # if they finish after I do, I go first
                    elif usage.get('end') > expected_end_time:
                        pass
                    # if they finish exactly at the same time I do
                    else:
                        if random.random() > 0.5:
                            # they go first
                            res.append(usage)
                        else:
                            # I go first
                            pass
                # if they start before I do and finish after I have started
                elif usage.get('init') < init_time < usage.get('end'):
                    res.append(usage)
        return res

    # def fill_statistics(self, action, current_pos=None, current_autonomy=None, current_time=None):
    #     if action.get('type') == 'PICK-UP':
    #         # distance from transport position to customer origin
    #         p1 = current_pos
    #         p2 = action.get('attributes').get('customer_origin')
    #         route = self.get_route(p1, p2)
    #         dist = route.get('distance')
    #         time = meters_to_seconds(dist)
    #         action['statistics']['dist'] = dist
    #         action['statistics']['time'] = time
    #
    #     elif action.get('type') == 'MOVE-TO-DEST':
    #         # distance from customer_origin to customer_destination
    #         p1 = action.get('attributes').get('customer_origin')
    #         p2 = action.get('attributes').get('customer_dest')
    #         route = self.get_route(p1, p2)
    #         dist = route.get('distance')
    #         time = meters_to_seconds(dist)
    #         action['statistics']['dist'] = dist
    #         action['statistics']['time'] = time
    #
    #     elif action.get('type') == 'MOVE-TO-STATION':
    #         # distance from transport position to station position
    #         p1 = current_pos
    #         p2 = action.get('attributes').get('station_position')
    #         route = self.get_route(p1, p2)
    #         dist = route.get('distance')
    #         time = meters_to_seconds(dist)
    #         action['statistics']['dist'] = dist
    #         action['statistics']['time'] = time
    #
    #     elif action.get('type') == 'CHARGE':
    #
    #         # Get variables
    #         agent = action.get('agent')
    #         station = action.get('attributes').get('station_id')
    #
    #         # 1. Compute charging time. The charge action will finish at the end of the charging time if there are
    #         # free places at the station
    #         need = self.agent_max_autonomy - current_autonomy
    #         charging_time = need / action.get('attributes').get('power')
    #
    #         # Nou check per veure si hi ha algú que està arribant exactament a la vegada que jo; si això passara,
    #         # m'incremente el meu temps d'arribada, recalcule els meus temps i torne a fer les comprovacions
    #         if self.db.check_simultaneous_charge(agent, station, current_time):
    #             current_time += 0.001
    #
    #         # 2. Check if there will be a free place to charge at the arrival to the station
    #         available_poles = self.db.check_available_poles(agent, station, current_time)
    #         if VERBOSE > 0:
    #             logger.info(
    #                 f"Evaluating charge action of agent {agent} in station {station} at time {current_time:.4f}")
    #             logger.info(f"There are {available_poles} available poles")
    #         #   2.2 If there is not, compute waiting time, add it to charging time to compute total time
    #         if available_poles == 0:
    #             queue, check = self.check_station_queue(agent, station, current_time)
    #             if VERBOSE > 0:
    #                 logger.info(f"There are {len(queue)} agents in front of {agent}")
    #             # Get que last X agents of the queue which are in front of you, where X is the number of stations
    #             # if check, there are more agents in front of me than places in the station
    #             if check:
    #                 # keep only last X to arrive
    #                 queue = queue[-self.db.get_station_places(station):]
    #             # if not check, there are as many agents in front of me as places in the station
    #             end_times = [x.get('end_charge') for x in queue]
    #             # Get charge init time
    #             init_charge = min(end_times)
    #             # end_charge = init_charge + charging_time
    #             # Compute waiting time
    #             waiting_time = init_charge - current_time
    #             if VERBOSE > 0:
    #                 logger.info(
    #                     f"Agent {agent} will begin charging at time {init_charge:.4f} after waiting {waiting_time:.4f} seconds")
    #         elif available_poles < 0:
    #             logger.critical(f"Error computing available poles: {available_poles} at time {current_time}")
    #             logger.debug("\n")
    #             logger.debug("Station usage:")
    #             for station in self.joint_plan.get('station_usage').keys():
    #                 if len(self.joint_plan.get('station_usage').get(station)) == 0:
    #                     logger.debug(f"{station:20s} : []")
    #                 else:
    #                     logger.debug(f"{station:20s} : [")
    #                     for usage in self.joint_plan.get('station_usage').get(station):
    #                         logger.debug(f"\t{usage.get('agent'):10s}, {usage.get('at_station'):.4f}, "
    #                                      f"{usage.get('init_charge'):.4f}, {usage.get('end_charge'):.4f}, "
    #                                      f"{usage.get('inv')}")
    #                     logger.debug("] \n")
    #         # if there are available poles
    #         else:
    #             init_charge = current_time
    #             waiting_time = 0
    #             if VERBOSE > 0:
    #                 logger.info(f"There are available places")
    #                 logger.info(
    #                     f"Agent {agent} will begin charging at time {init_charge:.4f} after waiting {waiting_time:.4f} seconds")
    #
    #         # Write times
    #         #   arrival at the station
    #         action['statistics']['at_station'] = current_time
    #         #   begin charging
    #         action['statistics']['init_charge'] = init_charge
    #         #   total time
    #         total_time = charging_time + waiting_time
    #         action['statistics']['time'] = total_time
    #         # amount (of something) to charge
    #         action['statistics']['need'] = need
    #
    #     return action

    def reachable_goal(self, customer_id, pick_up_time):
        if DEBUG: logger.warning(
            f'Checking if agent {self.agent_id} can pick-up customer {customer_id} at time {pick_up_time}')
        tup = self.table_of_goals.get(customer_id)
        if DEBUG: logger.warning(f'Customer {customer_id} is being served by {tup[0]} at time {tup[1]}')
        if tup[0] == self.agent_id:
            if DEBUG: logger.warning(
                f'Agent {self.agent_id} CAN pick-up customer {customer_id} because it was already serving it')
            return True
        elif pick_up_time < tup[1]:
            if DEBUG: logger.warning(
                f'Agent {self.agent_id} CAN pick-up customer {customer_id} because serves it at time {pick_up_time}')
            return True
        if DEBUG: logger.warning(f'Agent {self.agent_id} CAN NOT pick-up customer {customer_id}')
        return False

    def check_prev_plan(self):
        if len(self.joint_plan) > 0:
            if self.joint_plan["individual"][self.agent_id] is not None:
                if self.joint_plan["individual"][self.agent_id].utility > 0:
                    self.best_solution_value = self.joint_plan["individual"][self.agent_id].utility
                    logger.warning(f"Using {self.best_solution_value} as lower bound for plan utility")

    def run(self):

        start = time.time()

        # self.initialize()

        self.check_prev_plan()

        # CREATION OF INITIAL NODES
        if VERBOSE > 1:
            logger.info("Creating initial nodes...")

        generate_charging = self.create_customer_nodes()

        # Generate initial charging nodes if:
        # 1) A customer was unreachable because of autonomy lack OR
        # 2) The vehicle autonomy is not full
        if generate_charging or (CHARGE_WHEN_NOT_FULL and self.agent_autonomy < self.agent_max_autonomy):
            self.create_charge_nodes()

        if VERBOSE > 1:
            logger.info(f'{len(self.open_nodes):5d} nodes have been created')
            logger.info(self.open_nodes)

        # MAIN LOOP
        if VERBOSE > 1:
            logger.info(
                "###################################################################################################")
            logger.info("Starting MAIN LOOP...")

        i = 0
        while self.open_nodes:
            i += 1
            if VERBOSE > 0:
                logger.info(f'\nIteration {i:5d}.')
                logger.error(f"Open nodes: {len(self.open_nodes)}")
            # if VERBOSE > 1:
            # logger.info(f"{self.open_nodes}")

            tup = heapq.heappop(self.open_nodes)
            value = -tup[0]

            if HEURISTIC:
                # This voids the search without heuristic value
                if value < self.best_solution_value:
                    if VERBOSE > 0:
                        logger.info(
                            f'The node f_value {value:.4f} is lower than the best solution value {self.best_solution_value:.4f}')
                    continue

            parent = tup[2]

            if VERBOSE > 0:
                logger.info(f"Node {tup} popped from the open_nodes")
            if VERBOSE > 1:
                parent.print_node()

            # If the last action is a customer service, consider charging
            # otherwise consider ONLY customer actions (avoids consecutive charging actions)
            consider_charge = False
            not_full = False
            if parent.actions[-1].get('type') == 'MOVE-TO-DEST':
                consider_charge = True

            if VERBOSE > 0:
                logger.info("Generating CUSTOMER children nodes...")
            # Generate one child node per customer left to serve and return whether some customer could not be
            # picked up because of autonomy
            generate_charging = self.create_customer_nodes(parent)
            customer_children = len(parent.children)
            if VERBOSE > 0:
                logger.info(f'{customer_children:5d} customer children have been created')

            # Add charging consideration when the autonomy is not full
            if CHARGE_WHEN_NOT_FULL:
                if parent.agent_autonomy < self.agent_max_autonomy:
                    if VERBOSE > 1:
                        logger.warning(
                            f'Node autonomy {parent.agent_autonomy} < max autonomy {self.agent_max_autonomy}')
                    not_full = True

            # logger.warning(f'{consider_charge}, {generate_charging}, {CHARGE_WHEN_NOT_FULL}, {not_full}')

            # if we consider charging actions AND during the creation of customer nodes there was a customer
            # that could not be reached because of autonomy, create charge nodes.
            if (consider_charge and generate_charging) or (CHARGE_WHEN_NOT_FULL and not_full):
                if VERBOSE > 0:
                    logger.info("Generating CHARGE children nodes...")
                self.create_charge_nodes(parent)
                charge_children = len(parent.children) - customer_children
                if VERBOSE > 0:
                    logger.info(f'{charge_children:5d} charge children have been created')

            # If after this process the node has no children, it is a solution Node
            if not parent.children:
                if VERBOSE > 0:
                    logger.info("The node had no children, so it is a SOLUTION node")

                # Modify node f-value to utility value (h = 0)
                evaluate_node(parent, self.db, solution=True)
                self.solution_nodes.append((parent, parent.value))
                self.check_update_best_solution(parent)

            # Update max queue length
            if len(self.open_nodes) > self.max_queue_length:
                self.max_queue_length = len(self.open_nodes)

        # END OF MAIN LOOP
        end = time.time()

        if VERBOSE > 0:
            logger.info(
                "###################################################################################################")
            logger.info("\nEnd of MAIN LOOP")
            if not self.save_partial_solutions:
                logger.info(f'{len(self.solution_nodes):5d} solution nodes found')
            else:
                logger.info(f'{len(self.solution_nodes):5d} solution nodes found (includes partial solutions)')
            # n = 1
            # for tup in self.solution_nodes:
            #     logger.info("\nSolution", n)
            #     tup[0].print_node()
            #     n += 1
            if self.best_solution is not None:
                logger.info("Best solution node:")
                self.best_solution.print_node()

        # When the process finishes, extract plan from the best solution node
        # with its corresponding table of goals
        if self.best_solution is not None:
            self.extract_plan(self.best_solution)
            if PRINT_PLAN:
                logger.info(self.plan.to_string_plan())

        # Print process statistics
        # if VERBOSE > 0:
        logger.info("Process statistics:")
        # Amount of generated nodes
        logger.info(f'\tGenerated nodes - {self.generated_nodes}')
        # Max queue length
        logger.info(f'\tMax. queue length - {self.max_queue_length}')

        logger.debug(f'\tPlanning process time: {end - start}')

    # TODO modify for fixed goals
    def create_customer_nodes(self, parent=None):


        self.db.reload_actions()
        agent_actions = self.db.actions_dic.get(self.agent_id)
        # agent_actions = self.actions_dic.get(self.agent_id)

        pick_up_actions = agent_actions.get("PICK-UP")
        move_to_dest_actions = agent_actions.get("MOVE-TO-DEST")
        generate_charging = False

        # Remove customers not assigned to the agent
        pick_up_actions = [a for a in pick_up_actions if
                           a.get('attributes').get('customer_id') in self.agent_goals]
        move_to_dest_actions = [a for a in move_to_dest_actions if
                                a.get('attributes').get('customer_id') in self.agent_goals]

        # Remove served customers from actions
        if parent is not None:
            pick_up_actions = [a for a in pick_up_actions if
                               a.get('attributes').get('customer_id') not in parent.already_served()]
            move_to_dest_actions = [a for a in move_to_dest_actions if
                                    a.get('attributes').get('customer_id') not in parent.already_served()]

        for tup in self.db.get_customer_couples(pick_up_actions, move_to_dest_actions):
            customer_to_serve = tup[0].get('attributes').get('customer_id')
            if DEBUG: logger.info(f'Planing to serve customer {customer_to_serve}')
            if parent is None:
                node = Node()
                node.agent_pos = self.agent_pos.copy()
                node.agent_autonomy = self.agent_autonomy
                node.agent_goals = self.agent_goals.copy()
            else:
                node = Node(parent)

            # Fill actions statistics
            action1 = tup[0].copy()
            action2 = tup[1].copy()
            #  Calculates the time and distance according to agent's current pos/autonomy
            action1 = self.db.fill_statistics(action1, current_pos=node.agent_pos)
            action2 = self.db.fill_statistics(action2)

            node.actions += [action1, action2]

            # Calculate pick_up time and check table of goals
            pick_up_time = node.init_time + node.actions[-2].get('statistics').get('time')
            customer_id = node.actions[-2].get('attributes').get('customer_id')
            # customer_id = node.actions[-2].get('attributes').get('customer_id').split('@')[0]
            # CANVI DE PROVA
            if not self.reachable_goal(customer_id, pick_up_time):
                # delete node object
                if DEBUG: logger.info(f'Customer {customer_to_serve} is unreachable because of TIME, deleting the node')
                del node
                continue

            # Check if there's enough autonomy to do the customer action
            customer_origin = node.actions[-2].get("attributes").get("customer_origin")
            customer_dest = node.actions[-1].get("attributes").get("customer_dest")
            if not has_enough_autonomy(node.agent_autonomy, node.agent_pos, customer_origin, customer_dest):
                # activate generation of station initial nodes
                generate_charging = True
                # delete node object
                if DEBUG: logger.info(
                    f'Customer {customer_to_serve} is unreachable because of CHARGE, deleting the node')
                del node
                continue

            if DEBUG: logger.info(f'Customer {customer_to_serve} is REACHABLE')

            # Once the actions are set, calculate node end time
            node.set_end_time()

            # Update position and autonomy
            node.agent_autonomy -= calculate_km_expense(node.agent_pos,
                                                        node.actions[-1].get('attributes').get('customer_origin'),
                                                        node.actions[-1].get('attributes').get('customer_dest'))
            node.agent_pos = node.actions[-1].get('attributes').get('customer_dest')

            # Add served customer to completed_goals
            init = node.init_time
            pick_up_duration = node.actions[-2].get('statistics').get('time')
            node.completed_goals.append(
                (node.actions[-1].get('attributes').get('customer_id'), init + pick_up_duration))

            if DEBUG: logger.info(f'Customer {customer_to_serve} picked up at time {init + pick_up_duration}')

            # Evaluate node
            value = evaluate_node(node, self.db)
            if self.best_solution_prune:
                # If the value is higher than best solution value, add node to open_nodes
                if value > self.best_solution_value:
                    # Add node to parent's children
                    if parent is not None:
                        parent.children.append(node)
                    # Push node in the priority queue
                    heapq.heappush(self.open_nodes, (-1 * value, id(node), node))
                    self.generated_nodes += 1
                    if DEBUG: logger.info(f"Node added to open nodes with value {value}")

                    if self.save_partial_solutions:
                        evaluate_node(node, self.db, solution=True)
                        if DEBUG: logger.info(f"Node saved as a partial solution with value {node.value}")
                        self.solution_nodes.append((node, node.value))
                        self.check_update_best_solution(node)
                else:
                    if DEBUG: logger.info(
                        f"Node discarded: its value {value} is below best solution value {self.best_solution_value}")
            else:
                if parent is not None:
                    parent.children.append(node)
                # Push node in the priority queue
                heapq.heappush(self.open_nodes, (-1 * value, id(node), node))
                self.generated_nodes += 1
                if DEBUG: logger.info(f"Node added to open nodes with value {value}")

                if self.save_partial_solutions:
                    evaluate_node(node, self.db, solution=True)
                    if DEBUG: logger.info(f"Node saved as a partial solution with value {node.value}")
                    self.solution_nodes.append((node, node.value))
                    self.check_update_best_solution(node)

        return generate_charging

    def create_charge_nodes(self, parent=None):
        # # dic_file = open(ACTIONS_FILE, "r")
        # # actions_dic = json.load(dic_file)
        # # agent_actions = actions_dic.get(self.agent_id)
        #
        # self.db.reload_actions()
        # agent_actions = self.db.actions_dic.get(self.agent_id)
        #
        # move_to_station_actions = agent_actions.get("MOVE-TO-STATION")
        # charge_actions = agent_actions.get("CHARGE")

        # Filter stations to consider only those within a distance of 2km
        if parent is None:
            agent_pos = self.agent_pos

        else:
            agent_pos = parent.agent_pos

        filtered_move_actions, filtered_charge_actions = self.db.filter_station_actions(self.agent_id, agent_pos)

        # for tup in get_station_couples(move_to_station_actions, charge_actions):
        for tup in self.db.get_station_couples(filtered_move_actions, filtered_charge_actions):
            if parent is None:
                node = Node()
                node.agent_pos = self.agent_pos
                node.agent_autonomy = self.agent_autonomy
                node.agent_goals = self.agent_goals
                current_time = 0
            else:
                node = Node(parent)
                current_time = parent.end_time

            # Fill actions statistics
            action1 = tup[0].copy()
            action2 = tup[1].copy()
            #  Calculates the time and distance according to agent's current pos/autonomy
            action1 = self.db.fill_statistics(action1, current_pos=node.agent_pos)
            current_time += action1.get('statistics').get('time')
            action2 = self.db.fill_statistics(action2, current_autonomy=node.agent_autonomy,
                                              agent_max_autonomy=self.agent_max_autonomy, current_time=current_time)

            node.actions += [action1, action2]

            # Once the actions are set, calculate node end time
            node.set_end_time()

            # Update position and autonomy after charge
            node.agent_autonomy = self.agent_max_autonomy
            node.agent_pos = node.actions[-2].get('attributes').get('station_position')

            # Evaluate node
            value = evaluate_node(node, self.db)

            if self.best_solution_prune:
                # If the value is higher than best solution value, add node to open_nodes
                if value > self.best_solution_value:
                    # Add node to parent's children
                    if parent is not None:
                        parent.children.append(node)
                    # Push node in the priority queue
                    heapq.heappush(self.open_nodes, (-1 * value, id(node), node))
                    self.generated_nodes += 1
            else:
                if parent is not None:
                    parent.children.append(node)
                # Push node in the priority queue
                heapq.heappush(self.open_nodes, (-1 * value, id(node), node))
                self.generated_nodes += 1

    def check_update_best_solution(self, node):
        if self.best_solution_value < node.value:
            if VERBOSE > 1:
                logger.info(f'The value of the best solution node increased from '
                            f'{self.best_solution_value:.4f} to {node.value:.4f}')
            self.best_solution = node
            self.best_solution_value = node.value

    def extract_plan(self, node):
        self.plan = Plan(node.actions, node.value, node.completed_goals)

    def greedy_initial_plan(self):

        logger.info(f"Creating greedy initial plan for agent {self.agent_id}")

        # Get actions
        dic_file = open(ACTIONS_FILE, "r")
        actions_dic = json.load(dic_file)
        agent_actions = actions_dic.get(self.agent_id)

        pick_up_actions = agent_actions.get("PICK-UP")
        move_to_dest_actions = agent_actions.get("MOVE-TO-DEST")

        move_to_station_actions = agent_actions.get("MOVE-TO-STATION")
        charge_actions = agent_actions.get("CHARGE")

        actions = []
        goals = self.agent_goals
        completed_goals = []

        while goals:

            # Get agent attributes
            current_position = self.agent_pos
            current_autonomy = self.agent_autonomy
            max_autonomy = self.agent_max_autonomy
            if not actions:
                current_time = 0
            else:
                current_time = sum([a.get('statistics').get('time') for a in actions])

            # -------------------- Closest customer selection phase --------------------

            #   Get move_to_dest actions of customers in goals
            customer_actions = [a for a in move_to_dest_actions if a.get('attributes').get('customer_id') in goals]
            customer_distances = []
            # For every customer save a tuple with its name and the distance of the route from the agent's current
            # position to its origin position
            for action in customer_actions:
                customer_distances.append(
                    (action.get('attributes').get('customer_id'),
                     self.db.get_route(current_position, action.get('attributes').get('customer_origin')).get('distance'))
                )
            #   Get tuple with closest customer
            logger.info(customer_distances)
            closest_goal = min(customer_distances, key=lambda x: x[1])
            #   Extract closest customer and delete it from goals
            customer = closest_goal[0]
            goals = [c for c in goals if c != customer]

            # -------------------- Plan building phase --------------------

            # Get customer actions
            action1 = [a for a in pick_up_actions if a.get('attributes').get('customer_id') == customer]
            action1 = action1[0]
            action2 = [a for a in move_to_dest_actions if a.get('attributes').get('customer_id') == customer]
            action2 = action2[0]

            # Fill statistics w.r.t. current position and autonomy
            action1 = self.db.fill_statistics(action1, current_pos=current_position)
            action2 = self.db.fill_statistics(action2)

            # Check autonomy, go to charge in closest station if necessary
            customer_origin = action1.get("attributes").get("customer_origin")
            customer_dest = action2.get("attributes").get("customer_dest")

            # Need to charge
            if not has_enough_autonomy(current_autonomy, current_position, customer_origin, customer_dest):

                # Before a charge, reload actions
                dic_file = open(ACTIONS_FILE, "r")
                actions_dic = json.load(dic_file)
                agent_actions = actions_dic.get(self.agent_id)

                move_to_station_actions = agent_actions.get("MOVE-TO-STATION")
                charge_actions = agent_actions.get("CHARGE")

                # Store customer in the open goals list again
                goals.insert(0, customer)

                # Get closest station to transport
                station_actions = [self.db.fill_statistics(a, current_pos=current_position) for
                                   a in
                                   move_to_station_actions]
                action1 = min(station_actions, key=lambda x: x.get("statistics").get("time"))
                station_id = action1.get('attributes').get('station_id')
                current_time += action1.get('statistics').get('time')

                # Get actions for that station and fill statistics w.r.t. current position and autonomy
                action2 = [a for a in charge_actions if a.get('attributes').get('station_id') == station_id]
                action2 = action2[0]

                action2 = self.db.fill_statistics(action2, current_autonomy=current_autonomy,
                                                  agent_max_autonomy=self.agent_max_autonomy, current_time=current_time)

                # Update position and autonomy after charge
                self.agent_pos = action1.get('attributes').get('station_position')
                self.agent_autonomy = max_autonomy

                # Add actions to action list
                actions += [action1, action2]

            # No need to charge
            else:
                # Add actions, update position and autonomy
                # Add actions to action list
                actions += [action1, action2]
                # Update position and autonomy
                self.agent_autonomy -= calculate_km_expense(current_position,
                                                            action2.get('attributes').get('customer_origin'),
                                                            action2.get('attributes').get('customer_dest'))
                self.agent_pos = action2.get('attributes').get('customer_dest')

                # Add served customer to completed_goals
                init = current_time
                pick_up_duration = action1.get('statistics').get('time')
                completed_goals.append(
                    (action2.get('attributes').get('customer_id'), init + pick_up_duration))

        # end of while loop

        # -------------------- Joint Plan update phase --------------------

        # Create plan with agent action list
        self.plan = Plan(actions, -1, completed_goals)
        utility = evaluate_plan(self.plan, self.db.joint_plan)
        self.plan.utility = utility

        logger.info(f"Agent {self.agent_id} initial plan:")
        logger.info(self.plan.to_string_plan())

    def plan_from_node(self):

        start = time.time()

        logger.debug(f'Planning from node:')
        self.start_node.print_node()

        self.open_nodes.append((0, 12345, self.start_node))

        if VERBOSE > 1:
            logger.info(f'{len(self.open_nodes):5d} nodes have been created')
            logger.info(self.open_nodes)

        # MAIN LOOP
        if VERBOSE > 1:
            logger.info(
                "###################################################################################################")
            logger.info("Starting MAIN LOOP...")

        i = 0
        # TODO planifique per a recollir només a un % de customer... (simulacions molt grans)
        while self.open_nodes:
            i += 1
            if VERBOSE > 0:
                logger.info(f'\nIteration {i:5d}.')
                logger.error(f"Open nodes: {len(self.open_nodes)}")

            tup = heapq.heappop(self.open_nodes)
            value = -tup[0]

            if HEURISTIC:
                # This voids the search without heuristic value
                if value < self.best_solution_value:
                    if VERBOSE > 0:
                        logger.info(
                            f'The node f_value {value:.4f} is lower than the best solution value {self.best_solution_value:.4f}')
                    continue

            parent = tup[2]

            if VERBOSE > 0:
                logger.info(f"Node {tup} popped from the open_nodes")
            if VERBOSE > 1:
                parent.print_node()

            # If the last action is a customer service, consider charging
            # otherwise consider ONLY customer actions (avoids consecutive charging actions)
            consider_charge = False
            not_full = False
            if parent.actions[-1].get('type') == 'MOVE-TO-DEST':
                consider_charge = True

            if VERBOSE > 0:
                logger.info("Generating CUSTOMER children nodes...")
            # Generate one child node per customer left to serve and return whether some customer could not be
            # picked up because of autonomy
            generate_charging = self.create_customer_nodes(parent)
            customer_children = len(parent.children)
            if VERBOSE > 0:
                logger.info(f'{customer_children:5d} customer children have been created')

            # Add charging consideration when the autonomy is not full
            if CHARGE_WHEN_NOT_FULL:
                if parent.agent_autonomy < self.agent_max_autonomy:
                    if VERBOSE > 1:
                        logger.warning(
                            f'Node autonomy {parent.agent_autonomy} < max autonomy {self.agent_max_autonomy}')
                    not_full = True

            # if we consider charging actions AND during the creation of customer nodes there was a customer
            # that could not be reached because of autonomy, create charge nodes.
            if (consider_charge and generate_charging) or (CHARGE_WHEN_NOT_FULL and not_full):
                if VERBOSE > 0:
                    logger.info("Generating CHARGE children nodes...")
                self.create_charge_nodes(parent)
                charge_children = len(parent.children) - customer_children
                if VERBOSE > 0:
                    logger.info(f'{charge_children:5d} charge children have been created')

            # If after this process the node has no children, it is a solution Node
            if not parent.children:
                if VERBOSE > 0:
                    logger.info("The node had no children, so it is a SOLUTION node")

                # Modify node f-value to utility value (h = 0)
                evaluate_node(parent, self.db, solution=True)
                self.solution_nodes.append((parent, parent.value))
                self.check_update_best_solution(parent)

            # Update max queue length
            if len(self.open_nodes) > self.max_queue_length:
                self.max_queue_length = len(self.open_nodes)

        # END OF MAIN LOOP
        end = time.time()

        if VERBOSE > 0:
            logger.info(
                "###################################################################################################")
            logger.info("\nEnd of MAIN LOOP")
            if not self.save_partial_solutions:
                logger.info(f'{len(self.solution_nodes):5d} solution nodes found')
            else:
                logger.info(f'{len(self.solution_nodes):5d} solution nodes found (includes partial solutions)')

            if self.best_solution is not None:
                logger.info("Best solution node:")
                self.best_solution.print_node()

        # When the process finishes, extract plan from the best solution node
        # with its corresponding table of goals
        if self.best_solution is not None:
            self.extract_plan(self.best_solution)
            if PRINT_PLAN:
                logger.info(self.plan.to_string_plan())

        # Print process statistics
        # if VERBOSE > 0:
        logger.info("Process statistics:")
        # Amount of generated nodes
        logger.info(f'\tGenerated nodes - {self.generated_nodes}')
        # # Amount of expanded nodes
        # logger.info(f'\tExpanded nodes - {self.expanded_nodes}')
        # Max queue length
        logger.info(f'\tMax. queue length - {self.max_queue_length}')

        logger.debug(f'\tPlanning process time: {end - start}')


if __name__ == '__main__':
    logger.error("To test the Planner by itself please use the test_planner() function in launcher.py")
