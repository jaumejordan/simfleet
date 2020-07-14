"""
Develops a plan for a TransportAgent
"""
import heapq
import json
import math

from generators_utils import has_enough_autonomy, calculate_km_expense
from plan import Plan, PlanEntry
from constants import SPEED, STARTING_FARE, PRICE_PER_kWh, PENALTY, PRICE_PER_KM

VERBOSE = 2  # 2, 1 or 0 according to verbosity level


def meters_to_seconds(distance_in_meters):
    # km/h to m/s
    speed = SPEED / 3.6
    time = distance_in_meters / speed
    return time


# Given two lists of actions, returns the pick_up / move-to-dest tuple for the same customer
def get_customer_couples(pick_up_actions, move_to_dest_actions):
    res = []
    for a in pick_up_actions:
        customer_id = a.get('attributes').get('customer_id')
        for b in move_to_dest_actions:
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
            self.agent_pos = parent.agent_pos.copy()
            self.agent_autonomy = parent.agent_autonomy #.copy()
            self.init_time = parent.end_time #.copy()
            self.actions = parent.actions.copy()
            self.completed_goals = parent.completed_goals.copy()

        # Independent values for every node
        #   own f-value
        self.value = None
        self.end_time = None
        # to store children node (if any)
        self.children = []

    def set_end_time(self):
        if self.parent is None:
            self.end_time = self.init_time + sum(a.get('statistics').get('time') for a in self.actions)
        else:
            self.end_time = sum(a.get('statistics').get('time') for a in self.actions)
        # We are adding the time of the parent's inherited action, which have been already added

    def already_served(self):
        res = []
        for tup in self.completed_goals:
            res.append(tup[0])
        return res

    def print_node(self):
        action_string = ""
        for a in self.actions:
            if a.get('type') in ['PICK-UP', 'MOVE-TO-DEST']:
                action_string += str((a.get('type'), a.get('attributes').get('customer_id'))) + ", "
            else:
                action_string += str((a.get('type'), a.get('attributes').get('station_id'))) + ", "
            if a == self.actions[-1]:
                action_string = action_string[:-2]
        print(
            f'(\tagent_position:\t{self.agent_pos}\n'
            f'\tagent_autonomy:\t{self.agent_autonomy}\n'
            f'\tactions:\t[{action_string}]\n'
            f'\tinit_time:\t{self.init_time:.4f}\n'
            f'\tend_time:\t{self.end_time:.4f}\n'
            f'\tvalue:\t{self.value:.4f}\n'
            f'\tcompleted_goals:\t{self.completed_goals}\n'
            f'\thas parent?:\t{self.parent is not None}\n'
            f'\thas children?:\t{len(self.children)}\t)'
        )


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

        self.create_table_of_goals()

    # Reads plan of every agent (joint plan) and fills the corresponding table of goals
    # If the joint plan is empty, creates an entry per customer and initialises its
    # pick-up time to infinity
    def create_table_of_goals(self):
        if len(self.joint_plan) == 0:
            for customer in self.config_dic.get("customers"):
                self.table_of_goals[customer.get("name")] = math.inf
        else: #extract from joint plan
            for customer in self.joint_plan.get('table_of_goals').keys():
                tup = self.joint_plan.get('table_of_goals').get(customer)
                if tup is None:
                    self.table_of_goals[customer] = math.inf
                else:
                    self.table_of_goals[customer] = tup[1] # tup[0] transport_agent, tup[1] pick_up_time

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
            # Considerar afegit el "power" de la station com a attribute de les accions "charge"
            total_time = need / self.get_station_power(action.get('attributes').get('station_id'))
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
            print("ERROR :: There is no route for key \"", key, "\" in the routes_dic")
            exit()
        return route

    def get_station_power(self, station_id):
        # station_id = station_id.split('@')[0]
        # print("get_station_power:", station_id)
        for s in self.config_dic.get('stations'):
            if s.get('name') == station_id:
                return s.get('power')

    def reachable_goal(self, customer_id, pick_up_time):

        return self.table_of_goals.get(customer_id) > pick_up_time

    # Returns the f value of a node
    def evaluate_node(self, node):
        # Calculate g value w.r.t Joint plan + node actions
        # taking into account charging congestions (implementar a futur)
        g = 0
        # Benefits
        benefits = 0
        for action in node.actions:
            if action.get('type') == 'MOVE-TO-DEST':
                benefits += STARTING_FARE + (action.get('statistics').get('dist') / 1000) * PRICE_PER_KM
        # Costs
        costs = 0
        for action in node.actions:
            # For actions that entail a movement, pay a penalty per km (10%)
            if action.get('type') != 'CHARGE':
            #i f action.get('type') not in ['MOVE-TO-STATION', 'CHARGE']:
                costs += PENALTY * (action.get('statistics').get('dist') / 1000)
            # For actions that entail charging, pay for the charged electricity
            # TODO
            # price increase if congestion (implementar a futur)
            else:
                costs += PRICE_PER_kWh * action.get('statistics').get('need')
        # Utility (or g value) = benefits - costs
        g = benefits - costs
        #if g < 0:
            # print("THE COSTS ARE HIGHER THANT THE BENEFITS")


        # Calculate h value w.r.t Table of Goals + node end time
        h = 0
        for key in self.table_of_goals.keys():
            if key not in node.already_served():
                if node.end_time < self.table_of_goals.get(key):
                    # extract distance of customer trip
                    customer_actions = self.actions_dic.get(self.agent_id).get('MOVE-TO-DEST')
                    customer_actions = [a for a in customer_actions if a.get('attributes').get('customer_id') == key]
                    action = customer_actions[0]
                    p1 = action.get('attributes').get('customer_origin')
                    p2 = action.get('attributes').get('customer_dest')
                    route = self.get_route(p1, p2)
                    dist = route.get('distance')
                    h += STARTING_FARE + (dist / 1000) * PRICE_PER_KM
                # calculate benefits
                #h += 0

        f_value = g + h
        node.value = f_value
        return f_value

    def run(self):
        # CREATION OF INITIAL NODES
        if VERBOSE > 1:
            print("Creating initial nodes...")
        #   We assume that autonomy is full at beginning, so initially we'll just consider
        #   one pick up action per every possible goal
        agent_actions = self.actions_dic.get(self.agent_id)

        pick_up_actions = agent_actions.get("PICK-UP")
        move_to_dest_actions = agent_actions.get("MOVE-TO-DEST")

        # # Fill actions statistics
        # #   Calculates the time and distance according to agent's current pos/autonomy
        # pick_up_actions = [self.fill_statistics(a, current_pos=self.agent_pos) for a in pick_up_actions]
        # move_to_dest_actions = [self.fill_statistics(a) for a in move_to_dest_actions]

        # Var to control if generating initial chargin nodes is necessary
        generate_charging = False

        # Create the corresponding node per action
        #   Create node, fill values, evaluate, add to priority queue if possible
        for tup in get_customer_couples(pick_up_actions, move_to_dest_actions):
            node = Node()
            node.agent_pos = self.agent_pos
            node.agent_autonomy = self.agent_autonomy

            # Fill actions statistics
            #  Calculates the time and distance according to agent's current pos/autonomy
            node.actions = [self.fill_statistics(tup[0], current_pos=node.agent_pos),
                            self.fill_statistics(tup[1])]

            # Check if there's enough autonomy to do the customer action
            #   only if initial autonomy is not full (implementar a futur)
            customer_origin = node.actions[-2].get("attributes").get("customer_origin")
            customer_dest = node.actions[-1].get("attributes").get("customer_dest")

            if not has_enough_autonomy(node.agent_autonomy, node.agent_pos, customer_origin, customer_dest):
                # activate generation of station initial nodes
                generate_charging = True
                # delete node object
                node = None
                continue

            # Calculate pick_up time and check table of goals
            pick_up_time = node.init_time + node.actions[-2].get('statistics').get('time')
            customer_id = node.actions[-2].get('attributes').get('customer_id')
            # customer_id = node.actions[-2].get('attributes').get('customer_id').split('@')[0]
            if not self.reachable_goal(customer_id, pick_up_time):
                # delete node object
                node = None
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
            #print(
            #    f'Node init time is {init} and the pick_up took {pick_up_duration} seconds so the pick_up_time is {init + pick_up_duration}')
            # print(f'as you can see here {node.actions[-2]}')
            node.completed_goals.append(
                (node.actions[-1].get('attributes').get('customer_id'), init + pick_up_duration))
            #node.completed_goals.append((node.actions[-1].get('attributes').get('customer_id'), pick_up_time))

            # Evaluate node
            value = self.evaluate_node(node)
            # Push node in the priority queue
            heapq.heappush(self.open_nodes, (-1 * value, id(node), node))

        # Once there is one node per possible customer action, if there was a customer action not possible to complete
        # because of autonomy, generate nodes with charging actions in every station
        if generate_charging:
            move_to_station_actions = agent_actions.get("MOVE-TO-STATION")
            charge_actions = agent_actions.get("CHARGE")

            # # Fill actions statistics
            # #   Calculates the time and distance according to agent's current pos/autonomy
            # move_to_station_actions = [self.fill_statistics(a, current_pos=self.agent_pos) for a in move_to_station_actions]
            # charge_actions = [self.fill_statistics(a, current_autonomy=self.agent_autonomy) for a in charge_actions]

            for tup in get_station_couples(move_to_station_actions, charge_actions):
                node = Node()
                node.agent_pos = self.agent_pos
                node.agent_autonomy = self.agent_autonomy

                # Fill actions statistics
                #  Calculates the time and distance according to agent's current pos/autonomy
                node.actions = [self.fill_statistics(tup[0], current_pos=node.agent_pos),
                                self.fill_statistics(tup[1], current_autonomy=node.agent_autonomy)]

                # Once the actions are set, calculate node end time
                node.set_end_time()

                # Update position and autonomy after charge
                node.agent_autonomy = self.agent_max_autonomy
                node.agent_pos = node.actions[-2].get('attributes').get('station_position')

                # Evaluate node
                value = self.evaluate_node(node)
                # Push node in the priority queue
                heapq.heappush(self.open_nodes, (-1 * value, id(node), node))

        if VERBOSE > 1:
            print(f'{len(self.open_nodes):5d} nodes have been created')
            print(self.open_nodes)
        # MAIN LOOP
        if VERBOSE > 1:
            print("###################################################################################################")
            print("Starting MAIN LOOP...")

        i = 0
        # Si volem evitar que es planifique per a recollir només a un % de customer...
        # TODO
        while self.open_nodes:
            i += 1
            if VERBOSE > 1:
                print(f'\nIteration {i:5d}.')
                print("Open nodes:", len(self.open_nodes), self.open_nodes)
            # print("I'M IN THE MAIN LOOP")
            tup = heapq.heappop(self.open_nodes)
            value = tup[0]
            if value < self.best_solution_value:
                if VERBOSE > 1:
                    print(f'The node f_value is lower than the best solution value')
                    continue
            parent = tup[2]
            if VERBOSE > 1:
                print("Node", tup, "popped from the open_nodes")
                parent.print_node()
            # If the last action is a customer service, consider charging
            # otherwise consider ONLY customer actions (avoids consecutive charging actions)
            consider_charge = False
            if parent.actions[-1].get('type') == 'MOVE-TO-DEST':
                consider_charge = True

            if VERBOSE > 1:
                print("Generating CUSTOMER children nodes...")
            # Generate one child node per customer left to serve and return whether some customer could not be
            # picked up because of autonomy
            generate_charging = self.create_customer_nodes(parent)
            customer_children = len(parent.children)
            if VERBOSE > 1:
                print(f'{customer_children:5d} customer children have been created')

            # print("CHECKING THAT THE PARENT WASN'T MODIFIED DURING CUSTOMER CHILDREN GENERATION")
            # parent.print_node()
            # if we consider charging actions AND during the creation of customer nodes there was a customer
            # that could not be reached because of autonomy, create charge nodes.
            if consider_charge and generate_charging:
                if VERBOSE > 1:
                    print("Generating CHARGE children nodes...")
                self.create_charge_nodes(parent)
                charge_children = len(parent.children) - customer_children
                if VERBOSE > 1:
                    print(f'{charge_children:5d} charge children have been created')

            # if VERBOSE > 1:
            #     print(f'{len(parent.children):5d} children have been created')

            # If after this process the node has no children, it is a solution Node
            if not parent.children:
                if VERBOSE > 1:
                    print("The node had no children, so it is a SOLUTION node")
                    self.solution_nodes.append((parent, parent.value))
                if self.best_solution_value < parent.value:
                    if VERBOSE > 1:
                        print(f'The value of the best solution node increased from '
                              f'{self.best_solution_value:.4f} to {parent.value:.4f}')
                    self.best_solution = parent
                    self.best_solution_value = parent.value

        # END OF MAIN LOOP
        if VERBOSE > 1:
            print("###################################################################################################")
            print("\nEnd of MAIN LOOP")
            print(f'{len(self.solution_nodes):5d} solution nodes found')
            print("Solution nodes:",self.solution_nodes)
            n = 1
            for tup in self.solution_nodes:
                print("\nSolution",n)
                tup[0].print_node()
                n += 1
            print("Best solution node:")
            self.best_solution.print_node()


        print(self.best_solution.actions)
        print(self.best_solution.completed_goals)

        # When the process finishes, extract plan from the best solution node
        # with its corresponding table of goals
        self.extract_plan(self.best_solution)

        self.plan.print_plan()

    def create_customer_nodes(self, parent):
        agent_actions = self.actions_dic.get(self.agent_id)
        pick_up_actions = agent_actions.get("PICK-UP")
        move_to_dest_actions = agent_actions.get("MOVE-TO-DEST")
        generate_charging = False

        # Remove served customers from actions
        pick_up_actions = [a for a in pick_up_actions if
                           a.get('attributes').get('customer_id') not in parent.already_served()]
        move_to_dest_actions = [a for a in move_to_dest_actions if
                                a.get('attributes').get('customer_id') not in parent.already_served()]

        for tup in get_customer_couples(pick_up_actions, move_to_dest_actions):
            node = Node(parent)

            # Fill actions statistics
            #  Calculates the time and distance according to agent's current pos/autonomy
            node.actions += [self.fill_statistics(tup[0], current_pos=node.agent_pos),
                             self.fill_statistics(tup[1])]

            # Check if there's enough autonomy to do the customer action
            customer_origin = node.actions[-2].get("attributes").get("customer_origin")
            customer_dest = node.actions[-1].get("attributes").get("customer_dest")

            if not has_enough_autonomy(node.agent_autonomy, node.agent_pos, customer_origin, customer_dest):
                # activate generation of station initial nodes
                generate_charging = True
                # delete node object
                node = None
                continue

            # Calculate pick_up time and check table of goals
            pick_up_time = node.init_time + node.actions[-2].get('statistics').get('time')
            customer_id = node.actions[-2].get('attributes').get('customer_id')
            # customer_id = node.actions[-2].get('attributes').get('customer_id').split('@')[0]
            if not self.reachable_goal(customer_id, pick_up_time):
                # delete node object
                node = None
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
            # TODO correct pick-up time calculation
            # print(f'Node init time is {init} and the pick_up took {pick_up_duration} seconds so the pick_up_time is {init+pick_up_duration}')
            node.completed_goals.append((node.actions[-1].get('attributes').get('customer_id'), init+pick_up_duration))

            # Evaluate node
            value = self.evaluate_node(node)

            # If the value is below the best solution value, add node to open_nodes
            if value > self.best_solution_value:
                # Add node to parent's children
                parent.children.append(node)
                # Push node in the priority queue
                heapq.heappush(self.open_nodes, (-1 * value, id(node), node))

        return generate_charging

    def create_charge_nodes(self, parent):
        agent_actions = self.actions_dic.get(self.agent_id)
        move_to_station_actions = agent_actions.get("MOVE-TO-STATION")
        charge_actions = agent_actions.get("CHARGE")

        for tup in get_station_couples(move_to_station_actions, charge_actions):
            node = Node(parent)

            # Fill actions statistics
            #  Calculates the time and distance according to agent's current pos/autonomy
            node.actions += [self.fill_statistics(tup[0], current_pos=node.agent_pos),
                             self.fill_statistics(tup[1], current_autonomy=node.agent_autonomy)]

            # Once the actions are set, calculate node end time
            node.set_end_time()

            # Update position and autonomy after charge
            node.agent_autonomy = self.agent_max_autonomy
            node.agent_pos = node.actions[-2].get('attributes').get('station_position')

            # Evaluate node
            value = self.evaluate_node(node)

            # If the value is below the best solution value, add node to open_nodes
            if value > self.best_solution_value:
                # Add node to parent's children
                parent.children.append(node)
                # Push node in the priority queue
                heapq.heappush(self.open_nodes, (-1 * value, id(node), node))

    def extract_plan(self, node):
        self.plan = Plan(node.actions, node.value, node.completed_goals)

def initialize():
    config_dic = {}
    global_actions = {}
    routes_dic = {}
    try:
        f2 = open("3_planner_config.json", "r")
        config_dic = json.load(f2)

        f2 = open("test-actions.json", "r")
        global_actions = json.load(f2)

        f2 = open("all-routes.json", "r")
        routes_dic = json.load(f2)

        return config_dic, global_actions, routes_dic
    except Exception as e:
        print(str(e))
        exit()


if __name__ == '__main__':

    config_dic, global_actions, routes_dic = initialize()

    agent_id = 'pacoautobusero'
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
    # planner.create_table_of_goals()
    planner.run()
