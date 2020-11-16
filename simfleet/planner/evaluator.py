import json
import math

from simfleet.planner.congestion import check_charge_congestion
from simfleet.planner.constants import STARTING_FARE, PRICE_PER_KM, TRAVEL_PENALTY, PRICE_PER_kWh, TIME_PENALTY, \
    INVALID_CHARGE_PENALTY, HEURISTIC, ROUTES_FILE, STATION_CONGESTION
from loguru import logger


def get_benefit(action):
    return STARTING_FARE + (action.get('statistics').get('dist') / 1000) * PRICE_PER_KM


def get_travel_cost(action):
    return TRAVEL_PENALTY * (action.get('statistics').get('dist') / 1000)


def get_charge_cost(action):
    return PRICE_PER_kWh * action.get('statistics').get('need')


def compute_benefits(action_list):
    benefits = 0
    for action in action_list:
        if action.get('type') == 'MOVE-TO-DEST':
            benefits += get_benefit(action) + 1000
    return benefits


# Action_list must be node.actions or plan.entries
# table of goals must be list of tuples or dictionary
def compute_costs(action_list, table_of_goals, joint_plan):
    costs = 0
    for action in action_list:
        # For actions that entail a movement, pay a penalty per km (10%)
        if action.get('type') != 'CHARGE':
            costs += get_travel_cost(action)

        # For actions that entail charging, pay for the charged electricity
        else:
            charge_cost = get_charge_cost(action)
            # costs += get_charge_cost(action)
            if action.get('inv') == 'INV':
                costs += INVALID_CHARGE_PENALTY
            else:
                # Create station usage from action
                agent = action.get('agent')
                station = action.get('attributes').get('station_id')
                at_station = action.get('statistics').get('at_station')
                init_charge = action.get('statistics').get('init_charge')
                end_time = at_station + action.get('statistics').get('time')
                inv = action.get('inv')
                usage = {
                    'agent': agent,
                    'at_station': at_station,
                    'init_charge': init_charge,
                    'end_charge': end_time,
                    'inv': inv
                }

                if STATION_CONGESTION:
                    congestion_cost = check_charge_congestion(usage, station, charge_cost, joint_plan)

                    if charge_cost != congestion_cost:
                        logger.warning(
                            f"Charging cost incremented by congestion from {charge_cost} to {congestion_cost}")
                        costs += congestion_cost
                else:
                    costs += charge_cost

        # For actions that pick up a customer, add waiting time as a cost
        if action.get('type') == 'PICK-UP':
            customer = action.get('attributes').get('customer_id')
            # Evaluating a node
            if isinstance(table_of_goals, list):
                for tup in table_of_goals:
                    if tup[0] == customer:
                        pick_up = tup
                        break
            # Evaluating a plan
            elif isinstance(table_of_goals, dict):
                customer = action.get('attributes').get('customer_id')
                pick_up = table_of_goals.get(customer)

            # Add waiting time to costs
            if isinstance(pick_up, tuple):
                costs += pick_up[1] * TIME_PENALTY
            else:
                costs += pick_up * TIME_PENALTY
    return costs


def get_route(p1, p2, routes_dic):
    key = str(p1) + ":" + str(p2)
    route = routes_dic.get(key)
    if route is None:
        # En el futur, demanar la ruta al OSRM
        logger.info(f"ERROR :: There is no route for key {key} in the routes_dic")
        exit()
    return route


def already_served(node):
    res = []
    for tup in node.completed_goals:
        res.append(tup[0])
    return res


def get_h_value(node, actions_dic, routes_dic):
    h = 0
    benefits = 0
    costs = 0
    agent_id = node.actions[0].get('agent')

    # Get a list with the non-served customers
    non_served_customers = [x for x in node.agent_goals if x not in already_served(node)]

    for customer in non_served_customers:
        # extract distance of customer trip
        customer_actions = actions_dic.get(agent_id).get('MOVE-TO-DEST')
        customer_actions = [a for a in customer_actions if
                            a.get('attributes').get('customer_id') == customer]
        action = customer_actions[0]
        p1 = action.get('attributes').get('customer_origin')
        p2 = action.get('attributes').get('customer_dest')
        route = get_route(p1, p2, routes_dic)
        dist = route.get('distance')
        action['statistics']['dist'] = dist
        # Consider service benefits + move-to-dest costs
        benefits += get_benefit(action) + 1000
        costs += get_travel_cost(action)

    h = benefits - costs
    return h


def evaluate_node_2(node, joint_plan, actions_dic=None, routes_dic=None, solution=False):
    benefits = compute_benefits(node.actions)
    costs = compute_costs(node.actions, node.completed_goals, joint_plan)

    # Utility (or g value) = benefits - costs
    g = benefits - costs

    # Calculate heuristic value
    h = 0
    # If the node is a solution, its h value is 0
    if not solution:
        if HEURISTIC:
            h = get_h_value(node, actions_dic, routes_dic)

    f_value = g + h
    node.value = f_value
    return f_value


def evaluate_plan_2(plan, joint_plan):
    action_list = [entry.action for entry in plan.entries]

    benefits = compute_benefits(action_list)
    # costs = compute_costs(action_list, joint_plan.get('table_of_goals'), joint_plan)
    costs = compute_costs(action_list, plan.table_of_goals, joint_plan)

    # Utility (or g value) = benefits - costs
    utility = benefits - costs

    return utility
