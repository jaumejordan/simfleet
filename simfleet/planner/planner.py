"""
Develops a plan for a TransportAgent
"""
import heapq
import json
import math
import random
import time

from loguru import logger

from simfleet.planner.constants import ACTIONS_FILE, HEURISTIC, PRINT_OUTPUT
from simfleet.planner.evaluator import evaluate_node, evaluate_plan
from simfleet.planner.generators_utils import has_enough_autonomy, calculate_km_expense
from simfleet.planner.node import Node
from simfleet.planner.plan import Plan

VERBOSE = 0  # 2, 1 or 0 according to verbosity level

DEBUG = False

PRINT_GOALS = False
PRINT_PLAN = False
CHARGE_WHEN_NOT_FULL = True


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

        self.planning_time = -1

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
                    if PRINT_OUTPUT > 0:
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

            if len(parent.already_served()) < len(parent.agent_goals):

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
        self.planning_time = end - start
        if PRINT_OUTPUT > 0:
            logger.info("Process statistics:")
            # Amount of generated nodes
            logger.info(f'\tGenerated nodes - {self.generated_nodes}')
            # Max queue length
            logger.info(f'\tMax. queue length - {self.max_queue_length}')

            logger.debug(f'\tPlanning process time: {self.planning_time:.3f} s')

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
                current_time = 0
            else:
                node = Node(parent)
                current_time = sum(a.get('statistics').get('time') for a in parent.actions) # parent.end_time

            # Fill actions statistics
            action1 = tup[0].copy()
            action2 = tup[1].copy()
            #  Calculates the time and distance according to agent's current pos/autonomy
            action1 = self.db.fill_statistics(action1, current_pos=node.agent_pos, current_time=current_time)
            action2 = self.db.fill_statistics(action2, current_time=current_time)

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
            if not has_enough_autonomy(node.agent_autonomy, action1.get('statistics').get('dist'), action2.get('statistics').get('dist')):
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
            node.agent_autonomy -= calculate_km_expense(action1.get('statistics').get('dist'), action2.get('statistics').get('dist'))

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

        # Filter stations to consider only those within a distance of 2km

        if parent is None:
            non_served_customers = self.agent_goals
            filtered_move_actions, filtered_charge_actions = self.db.filter_station_actions(self.agent_id,
                                                                                            self.agent_pos,
                                                                                            self.agent_autonomy,
                                                                                            non_served_customers)
        else:
            non_served_customers = [x for x in self.agent_goals if x not in parent.already_served()]
            filtered_move_actions, filtered_charge_actions = self.db.filter_station_actions(self.agent_id,
                                                                                            parent.agent_pos,
                                                                                            parent.agent_autonomy,
                                                                                            non_served_customers)

        if len(filtered_move_actions) > 0:

            for tup in self.db.get_station_couples(filtered_move_actions, filtered_charge_actions):
                if parent is None:
                    node = Node()
                    node.agent_pos = self.agent_pos
                    node.agent_autonomy = self.agent_autonomy
                    node.agent_goals = self.agent_goals
                    current_time = 0
                else:
                    node = Node(parent)
                    current_time = sum(a.get('statistics').get('time') for a in parent.actions)

                # Fill actions statistics
                action1 = tup[0].copy()
                action2 = tup[1].copy()

                #  Calculates the time and distance according to agent's current pos/autonomy
                action1 = self.db.fill_statistics(action1, current_pos=node.agent_pos, current_time=current_time)
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
        if PRINT_OUTPUT > 0:
            logger.info(f"Creating greedy initial plan for agent {self.agent_id}")

        # Get actions

        agent_actions = self.db.actions_dic.get(self.agent_id)

        pick_up_actions = agent_actions.get("PICK-UP")
        move_to_dest_actions = agent_actions.get("MOVE-TO-DEST")

        actions = []
        goals = self.agent_goals
        completed_goals = []

        while goals:

            # Get agent attributes
            current_position = self.agent_pos
            current_autonomy = self.agent_autonomy
            max_autonomy = self.agent_max_autonomy
            if len(actions) == 0:
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
                     self.db.get_route(current_position, action.get('attributes').get('customer_origin')).get(
                         'distance'))
                )
            #   Get tuple with closest customer
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
            action1 = self.db.fill_statistics(action1, current_pos=current_position, current_time=current_time)
            action2 = self.db.fill_statistics(action2, current_time=current_time)

            # Check autonomy, go to charge in closest station if necessary
            customer_origin = action1.get("attributes").get("customer_origin")
            customer_dest = action2.get("attributes").get("customer_dest")

            # Need to charge
            if not has_enough_autonomy(current_autonomy, action1.get('statistics').get('dist'), action2.get('statistics').get('dist')):

                # Before a charge, reload actions
                self.db.reload_actions()
                agent_actions = self.db.actions_dic.get(self.agent_id)

                pick_up_actions = agent_actions.get("PICK-UP")
                move_to_dest_actions = agent_actions.get("MOVE-TO-DEST")

                move_to_station_actions = agent_actions.get("MOVE-TO-STATION")
                charge_actions = agent_actions.get("CHARGE")

                # Store customer in the open goals list again
                goals.insert(0, customer)

                # Get closest station to transport
                station_actions = [self.db.fill_statistics(a, current_pos=current_position, current_time=current_time) for
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
                self.agent_autonomy -= calculate_km_expense(action1.get('statistics').get('dist'), action2.get('statistics').get('dist'))
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
        utility = evaluate_plan(self.plan, self.db)
        self.plan.utility = utility
        if PRINT_OUTPUT > 0:
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
        if PRINT_OUTPUT > 0:
            logger.info("Process statistics:")
            # Amount of generated nodes
            logger.info(f'\tGenerated nodes - {self.generated_nodes}')
            # # Amount of expanded nodes
            # logger.info(f'\tExpanded nodes - {self.expanded_nodes}')
            # Max queue length
            logger.info(f'\tMax. queue length - {self.max_queue_length}')

            logger.debug(f'\tPlanning process time: {end - start:.3f}')


if __name__ == '__main__':
    logger.error("To test the Planner by itself please use the test_planner() function in launcher.py")
