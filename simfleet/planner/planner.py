"""
Develops a plan for a TransportAgent
"""
import heapq
import json
import math

from generators_utils import has_enough_autonomy, calculate_km_expense

# heapq.heappush(customers, (2, "Harry"))
# heapq.heappush(customers, (3, "Charles"))
# heapq.heappush(customers, (1, "Riya"))
# heapq.heappush(customers, (4, "Stacy"))

SPEED = 2000  # km/h
STARTING_FARE = 1.45
PRICE_PER_KM = 1.08
PENALTY = 0.1  # 10% of the traveled km
PRICE_PER_kWh = 0.0615


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
            self.agent_pos = parent.agent_pos
            self.agent_autonomy = parent.agent_autonomy
            self.init_time = parent.end_time
            self.actions = parent.actions
            self.completed_goals = parent.completed_goals

        # Independent values for every node
        #   own f-value
        self.value = None
        self.end_time = None
        # to store children node (if any)
        self.children = []

    def set_end_time(self):
        self.end_time = self.init_time + sum(a.get('statistics').get('time') for a in self.actions)

    def print_node(self):
        print(
            f'(\tposition:\t{self.agent_pos}\n\tautonomy:\t{self.agent_autonomy}\n\tactions:\t{self.actions}\t),\t{self.value}')
        if self.children:
            print(f'children -----------------------')
            for n in self.children:
                n.print_node()
            print(f'--------------------------------')


class Planner:
    def __init__(self, config_dic, actions_dic, routes_dic, agent_id, agent_pos, agent_max_autonomy, agent_autonomy,
                 joint_plan=None):

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
            joint_plan = []
        self.joint_plan = joint_plan
        # Best solution to prune tree
        self.best_solution = None
        self.best_solution_value = math.inf

    # Reads plan of every agent (joint plan) and fills the corresponding table of goals
    # If the joint plan is empty, creates an entry per customer and initialises its
    # pick-up time to infinity
    def create_table_of_goals(self):
        if not self.joint_plan:
            for customer in self.config_dic.get("customers"):
                self.table_of_goals[customer.get("name")] = math.inf

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
                benefits += STARTING_FARE + action.get('statistics').get('dist') / 1000 * PRICE_PER_KM
        # Costs
        costs = 0
        for action in node.actions:
            # For actions that entail a movement, pay a penalty per km (10%)
            if action.get('type') != 'CHARGE':
                costs += PENALTY * action.get('statistics').get('dist') / 1000
            # For actions that entail charging, pay for the charged electricity
            # price increase if congestion (implementar a futur)
            else:
                costs += PRICE_PER_kWh * action.get('statistics').get('need')
        # Utility (or g value) = benefits - costs
        g = benefits - costs

        # Calculate h value w.r.t Table of Goals + node end time
        h = 0
        for key in self.table_of_goals.keys():
            if node.end_time < self.table_of_goals.get(key):
                h += 1

        f_value = g + h
        node.value = f_value
        return f_value

    def run(self):
        # CREATION OF INITIAL NODES
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
                break

            # Calculate pick_up time and check table of goals
            pick_up_time = node.init_time + node.actions[-2].get('statistics').get('time')
            customer_id = node.actions[-2].get('attributes').get('customer_id')
            # customer_id = node.actions[-2].get('attributes').get('customer_id').split('@')[0]
            if not self.reachable_goal(customer_id, pick_up_time):
                # delete node object
                node = None
                break

            # Once the actions are set, calculate node end time
            node.set_end_time()
            # Update position and autonomy
            node.agent_autonomy -= calculate_km_expense(node.agent_pos,
                                                        node.actions[-1].get('attributes').get('customer_origin'),
                                                        node.actions[-1].get('attributes').get('customer_dest'))
            node.agent_pos = node.actions[-1].get('attributes').get('customer_dest')

            # Add served customer to completed_goals
            node.completed_goals.append(node.actions[-1].get('attributes').get('customer_id'))

            # Evaluate node
            value = self.evaluate_node(node)
            # Push node in the priority queue
            heapq.heappush(self.open_nodes, (-1 * value, node))

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
                heapq.heappush(self.open_nodes, (-1 * value, node))

        print(self.open_nodes)
        for tuple in self.open_nodes:
            node = tuple[1]
            print(node.print_node())

        # MAIN LOOP
        while self.open_nodes:
            node = heapq.heappop(self.open_nodes)[1]
            # If the last action is a customer service, consider charging
            # otherwise consider ONLY customer actions (avoids consecutive charging actions)
            consider_charge = False
            if node.actions[-1].get('type') == 'MOVE-TO-DEST':
                consider_charge = True

            # Generate one child node per customer left to serve and return whether some customer could not be
            # picked up because of autonomy
            generate_charging = self.create_customer_nodes(node)
            # if we consider charging actions AND during the creation of customer nodes there was a customer
            # that could not be reached because of autonomy, create charge nodes.
            if consider_charge and generate_charging:
                self.create_charge_nodes(node)

            # If after this process the node has no children, it is a solution Node
            if not node.children:
                if self.best_solution_value < node.value:
                    self.best_solution = node
                    self.best_solution_value = node.value

        print(self.open_nodes)
        for tuple in self.open_nodes:
            node = tuple[1]
            print(node.print_node())
        # END OF MAIN LOOP

        # When the process finishes, extract plan from the best solution node
        # with its corresponding table of goals
        self.extract_plan(self.best_solution)

    def create_customer_nodes(self, parent):
        agent_actions = self.actions_dic.get(self.agent_id)
        pick_up_actions = agent_actions.get("PICK-UP")
        move_to_dest_actions = agent_actions.get("MOVE-TO-DEST")
        generate_charging = False

        # Remove served customers from actions
        for a in pick_up_actions:
            if a.get('attributes').get('customer_id') in parent.completed_goals:
                pick_up_actions.remove(a)
        for a in move_to_dest_actions:
            if a.get('attributes').get('customer_id') in parent.completed_goals:
                move_to_dest_actions.remove(a)

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
                break

            # Calculate pick_up time and check table of goals
            pick_up_time = node.init_time + node.actions[-2].get('statistics').get('time')
            customer_id = node.actions[-2].get('attributes').get('customer_id')
            # customer_id = node.actions[-2].get('attributes').get('customer_id').split('@')[0]
            if not self.reachable_goal(customer_id, pick_up_time):
                # delete node object
                node = None
                break

            # Once the actions are set, calculate node end time
            node.set_end_time()
            # Update position and autonomy
            node.agent_autonomy -= calculate_km_expense(node.agent_pos,
                                                        node.actions[-1].get('attributes').get('customer_origin'),
                                                        node.actions[-1].get('attributes').get('customer_dest'))
            node.agent_pos = node.actions[-1].get('attributes').get('customer_dest')

            # Add served customer to completed_goals
            node.completed_goals.append(node.actions[-1].get('attributes').get('customer_id'))

            # Evaluate node
            value = self.evaluate_node(node)

            # If the value is below the best solution value, add node to open_nodes
            if value < self.best_solution_value:
                # Add node to parent's children
                parent.children.append(node)
                # Push node in the priority queue
                heapq.heappush(self.open_nodes, (-1 * value, node))

        return generate_charging

    def create_charge_nodes(self, parent):
        agent_actions = self.actions_dic.get(self.agent_id)
        move_to_station_actions = agent_actions.get("MOVE-TO-STATION")
        charge_actions = agent_actions.get("CHARGE")

        for tup in get_station_couples(move_to_station_actions, charge_actions):
            node = Node(parent)

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

            # If the value is below the best solution value, add node to open_nodes
            if value < self.best_solution_value:
                # Add node to parent's children
                parent.children.append(node)
                # Push node in the priority queue
                heapq.heappush(self.open_nodes, (-1 * value, node))


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
    planner.create_table_of_goals()
    planner.run()
    n1 = Node(None)
    n1.agent_pos = -90
    n1.agent_autonomy = 32

    n2 = Node(n1)
    n1.children.append(n2)

    n1.print_node()
