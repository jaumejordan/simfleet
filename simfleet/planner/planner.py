"""
Develops a plan for a TransportAgent
"""
import heapq
import json
import math

from loguru import logger

from simfleet.planner.constants import SPEED, STARTING_FARE, PRICE_PER_kWh, PENALTY, PRICE_PER_KM, CONFIG_FILE, \
    ACTIONS_FILE, ROUTES_FILE, get_travel_cost, get_charge_cost, get_benefit, GOAL_PERCENTAGE
from simfleet.planner.generators_utils import has_enough_autonomy, calculate_km_expense
from simfleet.planner.plan import Plan

VERBOSE = 2  # 2, 1 or 0 according to verbosity level
PRINT_GOALS = False
PRINT_PLAN = False

# TODO tenir en compte el nombre de places de l'estació de càrrega

def meters_to_seconds(distance_in_meters):
    # km/h to m/s
    speed = SPEED / 3.6
    time = distance_in_meters / speed
    return time


# Given two lists of actions, returns the pick_up / move-to-dest tuple for the same customer
def get_customer_couples(pick_up_actions, move_to_dest_actions):
    res = []
    for a in pick_up_actions[:]:
        customer_id = a.get('attributes').get('customer_id')
        for b in move_to_dest_actions[:]:
            if b.get('attributes').get('customer_id') == customer_id:
                res.append((a, b))
    return res


# Given two lists of actions, returns the move-to-station / charge tuple for the same station
def get_station_couples(move_to_station_actions, charge_actions):
    res = []
    for a in move_to_station_actions:
        station_id = a.get('attributes').get('station_id')
        for b in charge_actions:
            if b.get('attributes').get('station_id') == station_id:
                res.append((a, b))
    return res


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
            #   completed goals: list with names of already served customers
            self.completed_goals = []

        # If there is parent, inherit attributes
        else:
            self.parent = parent
            self.agent_pos = parent.agent_pos[:]
            self.agent_autonomy = parent.agent_autonomy  # .copy()
            self.init_time = parent.end_time  # .copy()
            self.actions = parent.actions[:]  # .copy()
            self.completed_goals = parent.completed_goals[:]  # .copy()

        # Independent values for every node
        #   own f-value
        self.value = None
        self.end_time = None
        # to store children node (if any)
        self.children = []

    def set_end_time(self):
        self.end_time = sum(a.get('statistics').get('time') for a in self.actions)

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
            f'(\n\tagent_position:\t{self.agent_pos}\n'
            f'\tagent_autonomy:\t{self.agent_autonomy}\n'
            f'\tactions:\t[{action_string}]\n'
            f'\tinit_time:\t{self.init_time:.4f}\n'
            f'\tend_time:\t{self.end_time:.4f}\n'
            f'\tvalue:\t{self.value:.4f}\n'
            f'\tcompleted_goals:\t{self.completed_goals}\n'
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
    def __init__(self, config_dic, actions_dic, routes_dic, agent_id, agent_pos, agent_max_autonomy, agent_autonomy,
                 previous_plan=None, joint_plan=None):

        # Precalculated routes and actions
        self.config_dic = config_dic
        self.actions_dic = actions_dic
        self.routes_dic = routes_dic

        # Transport agent attributes
        self.agent_id = agent_id
        self.agent_pos = agent_pos
        self.agent_max_autonomy = agent_max_autonomy
        self.agent_autonomy = agent_autonomy

        # Table of goals
        self.table_of_goals = {}
        # Node heap
        self.open_nodes = []
        # Joint plan
        if joint_plan is None:
            joint_plan = {}
        self.joint_plan = joint_plan
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
        self.save_partial_solutions = True
        self.best_solution_prune = True

        # Planner statistics
        self.generated_nodes = 0
        self.expanded_nodes = 0
        self.max_queue_length = 0

        self.create_table_of_goals()


    # Reads plan of every agent (joint plan) and fills the corresponding table of goals
    # If the joint plan is empty, creates an entry per customer and initialises its
    # pick-up time to infinity
    def create_table_of_goals(self):
        if len(self.joint_plan) == 0:
            for customer in self.config_dic.get("customers"):
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

    def fill_statistics(self, action, current_pos=None, current_autonomy=None):
        if action.get('type') == 'PICK-UP':
            # distance from transport position to customer origin
            p1 = current_pos
            p2 = action.get('attributes').get('customer_origin')
            route = self.get_route(p1, p2)
            dist = route.get('distance')
            time = meters_to_seconds(dist)
            action['statistics']['dist'] = dist
            action['statistics']['time'] = time

        elif action.get('type') == 'MOVE-TO-DEST':
            # distance from customer_origin to customer_destination
            p1 = action.get('attributes').get('customer_origin')
            p2 = action.get('attributes').get('customer_dest')
            route = self.get_route(p1, p2)
            dist = route.get('distance')
            time = meters_to_seconds(dist)
            action['statistics']['dist'] = dist
            action['statistics']['time'] = time

        elif action.get('type') == 'MOVE-TO-STATION':
            # distance from transport position to station position
            p1 = current_pos
            p2 = action.get('attributes').get('station_position')
            route = self.get_route(p1, p2)
            dist = route.get('distance')
            time = meters_to_seconds(dist)
            action['statistics']['dist'] = dist
            action['statistics']['time'] = time

        elif action.get('type') == 'CHARGE':
            need = self.agent_max_autonomy - current_autonomy
            total_time = need / action.get('attributes').get('power')
            # time to complete the charge
            action['statistics']['time'] = total_time
            # amount (of something) to charge
            action['statistics']['need'] = need

        return action

    def get_route(self, p1, p2):
        key = str(p1) + ":" + str(p2)
        route = self.routes_dic.get(key)
        if route is None:
            # En el futur, demanar la ruta al OSRM
            logger.info("ERROR :: There is no route for key \"", key, "\" in the routes_dic")
            exit()
        return route

    def get_number_of_customers(self):
        return len(self.config_dic.get('customers'))

    def reachable_goal(self, customer_id, pick_up_time):
        tup = self.table_of_goals.get(customer_id)
        if tup[0] == self.agent_id:
            return True
        elif pick_up_time < tup[1]:
            return True
        # if pick_up_time < tup[1]:
        #     return True
        return False

    # Returns the f value of a node
    def evaluate_node(self, node, solution=False):
        # Calculate g value w.r.t Joint plan + node actions
        # taking into account charging congestions (implementar a futur)
        g = 0
        # Benefits
        benefits = 0
        for action in node.actions:
            if action.get('type') == 'MOVE-TO-DEST':
                benefits += get_benefit(action)
        # Costs
        costs = 0
        for action in node.actions:
            # For actions that entail a movement, pay a penalty per km (10%)
            if action.get('type') != 'CHARGE':
                # i f action.get('type') not in ['MOVE-TO-STATION', 'CHARGE']:
                costs += get_travel_cost(action)
            # For actions that entail charging, pay for the charged electricity
            # TODO price increase if congestion (implementar a futur)
            else:
                costs += get_charge_cost(action)
        # Utility (or g value) = benefits - costs
        g = benefits - costs

        # Calculate h value w.r.t Table of Goals + node end time
        h = 0
        # If the node is a solution, its h value is 0
        if not solution:
            h = self.get_h_value(node)

        f_value = g + h
        node.value = f_value
        return f_value

    def get_h_value(self, node):
        h = 0
        for key in self.table_of_goals.keys():
            if key not in node.already_served():
                if node.end_time < self.table_of_goals.get(key)[1]:
                    # extract distance of customer trip
                    customer_actions = self.actions_dic.get(self.agent_id).get('MOVE-TO-DEST')
                    customer_actions = [a for a in customer_actions if
                                        a.get('attributes').get('customer_id') == key]
                    action = customer_actions[0]
                    p1 = action.get('attributes').get('customer_origin')
                    p2 = action.get('attributes').get('customer_dest')
                    route = self.get_route(p1, p2)
                    dist = route.get('distance')
                    h += STARTING_FARE + (dist / 1000) * PRICE_PER_KM
        return h

    def check_prev_plan(self):
        if len(self.joint_plan) > 0:
            if self.joint_plan["individual"][self.agent_id] is not None:
                if self.joint_plan["individual"][self.agent_id].utility > 0:
                    self.best_solution_value = self.joint_plan["individual"][self.agent_id].utility
                    logger.warning(f"Using {self.best_solution_value} as lower bound for plan utility")

    def purge_open_nodes(self):
        init_len = len(self.open_nodes)
        self.open_nodes = [x for x in self.open_nodes if -1 * x[0] > self.best_solution_value]
        final_len = len(self.open_nodes)

        if final_len < init_len:
            heapq.heapify(self.open_nodes)
            if VERBOSE > 1:
                logger.debug(f"{init_len - final_len} nodes where purged from the list of open nodes")
        elif final_len == final_len:
            if VERBOSE > 1:
                logger.debug(f"No node was purged")
        else:
            logger.critical("ERROR :: There are more nodes after the purge!!!")

    def run(self):
        self.check_prev_plan()
        logger.debug(
            f"Planning to complete a {GOAL_PERCENTAGE * 100}% of the goals: {self.get_number_of_customers() * GOAL_PERCENTAGE:.0f} customers.")
        # CREATION OF INITIAL NODES
        if VERBOSE > 1:
            logger.info("Creating initial nodes...")

        generate_charging = self.create_customer_nodes()

        if generate_charging:
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
        # TODO planifique per a recollir només a un % de customer... (simulacions molt grans)
        while self.open_nodes:
            i += 1
            if VERBOSE > 0:
                logger.info(f'\nIteration {i:5d}.')
                logger.error(f"Open nodes: {len(self.open_nodes)}")
                logger.info(f"{self.open_nodes}")

            tup = heapq.heappop(self.open_nodes)
            value = -tup[0]

            if value < self.best_solution_value:
                if VERBOSE > 0:
                    logger.info(
                        f'The node f_value {value:.4f} is lower than the best solution value {self.best_solution_value:.4f}')
                continue

            parent = tup[2]
            self.expanded_nodes += 1

            if VERBOSE > 0:
                logger.info("Node", tup, "popped from the open_nodes")
            if VERBOSE > 1:
                parent.print_node()

            # if the plan in the node picks up a % of the customers, consider it complete
            if not len(parent.completed_goals) / self.get_number_of_customers() >= GOAL_PERCENTAGE:

                # If the last action is a customer service, consider charging
                # otherwise consider ONLY customer actions (avoids consecutive charging actions)
                consider_charge = False
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

                # if we consider charging actions AND during the creation of customer nodes there was a customer
                # that could not be reached because of autonomy, create charge nodes.
                if consider_charge and generate_charging:
                    if VERBOSE > 0:
                        logger.info("Generating CHARGE children nodes...")
                    self.create_charge_nodes(parent)
                    charge_children = len(parent.children) - customer_children
                    if VERBOSE > 0:
                        logger.info(f'{charge_children:5d} charge children have been created')
            else:
                if VERBOSE > 0:
                    logger.info("The node completed a % of the total goals")

            # If after this process the node has no children, it is a solution Node
            if not parent.children:
                if VERBOSE > 0:
                    logger.info("The node had no children, so it is a SOLUTION node")

                # Modify node f-value to utility value (h = 0)
                self.evaluate_node(parent, solution=True)
                self.solution_nodes.append((parent, parent.value))
                self.check_update_best_solution(parent)

            # Update max queue length
            if len(self.open_nodes) > self.max_queue_length:
                self.max_queue_length = len(self.open_nodes)

        # END OF MAIN LOOP
        if VERBOSE > 0:
            logger.info(
                "###################################################################################################")
            logger.info("\nEnd of MAIN LOOP")
            if not self.save_partial_solutions:
                logger.info(f'{len(self.solution_nodes):5d} solution nodes found')
            else:
                logger.info(f'{len(self.solution_nodes):5d} solution nodes found (includes partial solutions)')
            n = 1
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
        if VERBOSE > 0:
            logger.info("Process statistics:")
            # Amount of generated nodes
            logger.info(f'\tGenerated nodes - {self.generated_nodes}')
            # Amount of expanded nodes
            logger.info(f'\tExpanded nodes - {self.expanded_nodes}')
            # Max queue length
            logger.info(f'\tMax. queue length - {self.max_queue_length}')

    def create_customer_nodes(self, parent=None):

        dic_file = open(ACTIONS_FILE, "r")
        actions_dic = json.load(dic_file)
        agent_actions = actions_dic.get(self.agent_id)
        # agent_actions = self.actions_dic.get(self.agent_id)

        pick_up_actions = agent_actions.get("PICK-UP")
        move_to_dest_actions = agent_actions.get("MOVE-TO-DEST")
        generate_charging = False

        # Remove served customers from actions
        if parent is not None:
            pick_up_actions = [a for a in pick_up_actions if
                               a.get('attributes').get('customer_id') not in parent.already_served()]
            move_to_dest_actions = [a for a in move_to_dest_actions if
                                    a.get('attributes').get('customer_id') not in parent.already_served()]

        for tup in get_customer_couples(pick_up_actions, move_to_dest_actions):
            if parent is None:
                node = Node()
                node.agent_pos = self.agent_pos.copy()
                node.agent_autonomy = self.agent_autonomy
            else:
                node = Node(parent)

            # Fill actions statistics
            action1 = tup[0].copy()
            action2 = tup[1].copy()
            #  Calculates the time and distance according to agent's current pos/autonomy
            action1 = self.fill_statistics(action1, current_pos=node.agent_pos)
            action2 = self.fill_statistics(action2)

            node.actions += [action1, action2]

            # Calculate pick_up time and check table of goals
            pick_up_time = node.init_time + node.actions[-2].get('statistics').get('time')
            customer_id = node.actions[-2].get('attributes').get('customer_id')
            # customer_id = node.actions[-2].get('attributes').get('customer_id').split('@')[0]
            # CANVI DE PROVA
            if not self.reachable_goal(customer_id, pick_up_time):
                # delete node object
                del node
                continue

            # Check if there's enough autonomy to do the customer action
            customer_origin = node.actions[-2].get("attributes").get("customer_origin")
            customer_dest = node.actions[-1].get("attributes").get("customer_dest")
            if not has_enough_autonomy(node.agent_autonomy, node.agent_pos, customer_origin, customer_dest):
                # activate generation of station initial nodes
                generate_charging = True
                # delete node object
                del node
                continue

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

            # Evaluate node
            value = self.evaluate_node(node)

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

            # EVALUATE NODE AS SOLUTION NODE AND SAVE IT AS SOLUTION
            # TODO
            if self.save_partial_solutions:
                self.evaluate_node(node, solution=True)
                self.solution_nodes.append((node, node.value))
                self.check_update_best_solution(node)

        return generate_charging

    def create_charge_nodes(self, parent=None):
        dic_file = open(ACTIONS_FILE, "r")
        actions_dic = json.load(dic_file)
        agent_actions = actions_dic.get(self.agent_id)
        # agent_actions = self.actions_dic.get(self.agent_id)
        move_to_station_actions = agent_actions.get("MOVE-TO-STATION")
        charge_actions = agent_actions.get("CHARGE")

        for tup in get_station_couples(move_to_station_actions, charge_actions):
            if parent is None:
                node = Node()
                node.agent_pos = self.agent_pos
                node.agent_autonomy = self.agent_autonomy
            else:
                node = Node(parent)

            # Fill actions statistics
            action1 = tup[0].copy()
            action2 = tup[1].copy()
            #  Calculates the time and distance according to agent's current pos/autonomy
            action1 = self.fill_statistics(action1, current_pos=node.agent_pos)
            action2 = self.fill_statistics(action2, current_autonomy=node.agent_autonomy)

            node.actions += [action1, action2]

            # Once the actions are set, calculate node end time
            node.set_end_time()

            # Update position and autonomy after charge
            node.agent_autonomy = self.agent_max_autonomy
            node.agent_pos = node.actions[-2].get('attributes').get('station_position')

            # Evaluate node
            value = self.evaluate_node(node)

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
        if self.best_solution_value <= node.value:
            if VERBOSE > 1:
                logger.info(f'The value of the best solution node increased from '
                            f'{self.best_solution_value:.4f} to {node.value:.4f}')
            self.best_solution = node
            self.best_solution_value = node.value
            # self.purge_open_nodes()

    def extract_plan(self, node):
        self.plan = Plan(node.actions, node.value, node.completed_goals)


def initialize():
    try:
        f2 = open(CONFIG_FILE, "r")
        config_dic = json.load(f2)

        f2 = open(ACTIONS_FILE, "r")
        global_actions = json.load(f2)

        f2 = open(ROUTES_FILE, "r")
        routes_dic = json.load(f2)

        return config_dic, global_actions, routes_dic
    except Exception as e:
        print(str(e))
        exit()


if __name__ == '__main__':

    config_dic, global_actions, routes_dic = initialize()

    agent_id = 'Bus'
    agent_pos = agent_max_autonomy = None
    for transport in config_dic.get('transports'):
        if transport.get('name') == agent_id:
            agent_pos = transport.get('position')
            agent_max_autonomy = transport.get('autonomy')
            agent_autonomy = transport.get('current_autonomy')
    # actions_dic, routes_dic, agent_id, agent_pos, agent_autonomy, joint_plan=None):
    planner = Planner(config_dic=config_dic,
                      actions_dic=global_actions,
                      routes_dic=routes_dic,
                      agent_id=agent_id,
                      agent_pos=agent_pos,
                      agent_max_autonomy=agent_max_autonomy,
                      agent_autonomy=agent_autonomy)
    planner.run()
