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
def get_couples(pick_up_actions, move_to_dest_actions):
    res = []
    for a in pick_up_actions:
        customer_id = a.get('attributes').get('customer_id')
        for b in move_to_dest_actions:
            if b.get('attributes').get('customer_id') == customer_id:
                res.append((a, b))
    return res


class Node:
    def __init__(self, parent=None):
        self.parent = parent
        self.agent_pos = None
        self.agent_autonomy = None
        self.init_time = 0.0
        self.end_time = None
        self.actions = []
        self.value = None
        self.children = []

    def set_end_time(self):
        self.end_time = sum(a.get('statistics').get('time') for a in self.actions)

    def print_node(self):
        print(
            f'(\tposition:\t{self.agent_pos}\n\tautonomy:\t{self.agent_autonomy}\n\tactions:\t{self.actions}\t),\t{self.value}')
        if self.children:
            print(f'children -----------------------')
            for n in self.children:
                n.print_node()
            print(f'--------------------------------')


class Planner:
    def __init__(self, config_dic, actions_dic, routes_dic, agent_id, agent_pos, agent_autonomy, joint_plan=None):

        # Precalculated routes and actions
        self.config_dic = config_dic
        self.actions_dic = actions_dic
        self.routes_dic = routes_dic

        # Transport agent attributes
        self.agent_id = agent_id
        self.agent_pos = agent_pos
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

    # Reads plan of every agent (joint plan) and fills the corresponding table of goals
    # If the joint plan is empty, creates an entry per customer and initialises its
    # pick-up time to infinity
    def create_table_of_goals(self):
        if not self.joint_plan:
            for customer in self.config_dic.get("customers"):
                self.table_of_goals[customer.get("name")] = math.inf

    def fill_statistics(self, action, current_pos=None):
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
            # Aquesta per a més endavant, que té més chicha...
            # time to complete the charge
            action['statistics']['time'] = 10.0
            # amount (of something) to charge
            action['statistics']['need'] = 30.0

        return action

    def get_route(self, p1, p2):
        key = str(p1) + ":" + str(p2)
        route = self.routes_dic.get(key)
        if route is None:
            # En el futur, demanar la ruta al OSRM
            print("ERROR :: There is no route for key \"", key,"\" in the routes_dic")
            exit()
        return route

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
                benefits += STARTING_FARE + action.get('statistics').get('dist')/1000 * PRICE_PER_KM
        # Costs
        costs = 0
        for action in node.actions:
            # For actions that entail a movement, pay a penalty per km (10%)
            if action.get('type') != 'CHARGE':
                costs += PENALTY * action.get('statistics').get('dist')/1000
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
        #   We assume that autonomy is full at beginning, so initially we'll just consider one pick up action per every possible goal
        agent_actions = self.actions_dic.get(self.agent_id)

        pick_up_actions = agent_actions.get("PICK-UP")
        move_to_dest_actions = agent_actions.get("MOVE-TO-DEST")
        # Fill actions statistics
        #   Calculates the time and distance according to agent's current pos/autonomy
        pick_up_actions = [self.fill_statistics(a, self.agent_pos) for a in pick_up_actions]
        move_to_dest_actions = [self.fill_statistics(a) for a in move_to_dest_actions]

        # Create the corresponding node per action
        #   Create node, fill values, evaluate, add to priority queue if possible
        for tup in get_couples(pick_up_actions, move_to_dest_actions):
            node = Node()
            node.agent_pos = self.agent_pos
            node.agent_autonomy = self.agent_autonomy
            node.actions = list(tup)

            # Calculate pick_up time and check table of goals
            pick_up_time = node.init_time + node.actions[-2].get('statistics').get('time')
            customer_id = node.actions[-2].get('attributes').get('customer_id').split('@')[0]
            if not self.reachable_goal(customer_id, pick_up_time):
                # delete node object
                node = None
                break

            # Check autonomy
            #   only if initial autonomy is not full (implementar a futur)

            # Once the actions are set, calculate node end time
            node.set_end_time()
            # Update position and autonomy
            node.agent_autonomy -= calculate_km_expense(node.agent_pos,
                                                        node.actions[-1].get('attributes').get('customer_origin'),
                                                        node.actions[-1].get('attributes').get('customer_dest'))
            node.agent_pos = node.actions[-1].get('attributes').get('customer_dest')

            # Evaluate node
            value = self.evaluate_node(node)
            # Push node in the priority queue
            heapq.heappush(self.open_nodes, (-1*value, node))

        print(self.open_nodes)
        for tuple in self.open_nodes:
            node = tuple[1]
            print(node.print_node())
        # BUCLE PRINCIPAL
        while self.open_nodes:
            node = self.open_nodes.pop()
            self.generate_children(node)
        # TO BE CONTINUED...

    def create_customer_node(self):
        return Node()

    def create_charge_node(self):
        return Node()


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
                      agent_autonomy=agent_max_autonomy)
    planner.create_table_of_goals()
    planner.run()
    n1 = Node(None)
    n1.agent_pos = -90
    n1.agent_autonomy = 32

    n2 = Node(n1)
    n1.children.append(n2)

    n1.print_node()
