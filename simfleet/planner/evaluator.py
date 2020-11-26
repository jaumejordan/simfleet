from loguru import logger

from simfleet.planner.congestion import check_charge_congestion, check_road_congestion
from simfleet.planner.constants import STARTING_FARE, PRICE_PER_KM, TRAVEL_PENALTY, PRICE_PER_kWh, TIME_PENALTY, \
    INVALID_CHARGE_PENALTY, HEURISTIC, STATION_CONGESTION, ROAD_CONGESTION, PRINT_OUTPUT


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
def compute_costs(action_list, table_of_goals, db):
    # New: only print warning when evaluating (or reevaluating) a plan, not a node
    # Evaluating a node
    node = False
    if isinstance(table_of_goals, list):
        node = True
    costs = 0
    for action in action_list:
        # For actions that entail a movement, pay a penalty per km (10%)
        if action.get('type') != 'CHARGE':
            travel_cost = get_travel_cost(action)
            if ROAD_CONGESTION:
                # Compute road congestion
                road_congestion = check_road_congestion(action, travel_cost, db)

                if travel_cost != road_congestion:
                    costs += road_congestion
                    if not node:
                        if PRINT_OUTPUT > 0:
                            logger.warning(
                                f"Travel cost incremented by congestion from {travel_cost} to {road_congestion}")
                else:
                    costs += travel_cost

        # For actions that entail charging, pay for the charged electricity
        else:
            charge_cost = get_charge_cost(action)
            if action.get('inv') == 'INV':
                costs += INVALID_CHARGE_PENALTY
            else:
                # Create station usage from action
                agent = action.get('agent')
                station = action.get('attributes').get('station_id')
                at_station = action.get('statistics').get('at_station')
                init_charge = action.get('statistics').get('init_charge')
                end_time = at_station + action.get('statistics').get('time')
                power = action.get('statistics').get('need')
                inv = action.get('inv')
                usage = {
                    'agent': agent,
                    'at_station': at_station,
                    'init_charge': init_charge,
                    'end_charge': end_time,
                    'power': power,
                    'inv': inv
                }

                if STATION_CONGESTION:
                    charge_congestion = check_charge_congestion(usage, station, charge_cost, db)

                    if charge_cost != charge_congestion:
                        if not node:
                            if PRINT_OUTPUT > 0:
                                logger.warning(
                                    f"Charging cost incremented by congestion from {charge_cost} to {charge_congestion}")
                        costs += charge_congestion
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


def already_served(node):
    res = []
    for tup in node.completed_goals:
        res.append(tup[0])
    return res


def get_h_value(node, db):

    benefits = 0
    costs = 0
    agent_id = node.actions[0].get('agent')

    # Get a list with the non-served customers
    non_served_customers = [x for x in node.agent_goals if x not in already_served(node)]

    for customer in non_served_customers:
        # extract distance of customer trip
        customer_actions = db.actions_dic.get(agent_id).get('MOVE-TO-DEST')
        customer_actions = [a for a in customer_actions if
                            a.get('attributes').get('customer_id') == customer]
        action = customer_actions[0]
        p1 = action.get('attributes').get('customer_origin')
        p2 = action.get('attributes').get('customer_dest')
        route = db.get_route(p1, p2)
        dist = route.get('distance')
        action['statistics']['dist'] = dist

        # Consider service benefits + move-to-dest costs
        benefits += get_benefit(action) + 1000
        costs += get_travel_cost(action)

    h = benefits - costs
    return h


def get_h_value_open_goals(self, node, db):
    h = 0
    for key in self.table_of_goals.keys():
        if key not in node.already_served():
            if node.end_time < self.table_of_goals.get(key)[1]:
                # extract distance of customer trip
                customer_actions = self.db.actions_dic.get(self.agent_id).get('MOVE-TO-DEST')
                customer_actions = [a for a in customer_actions if
                                    a.get('attributes').get('customer_id') == key]
                action = customer_actions[0]
                p1 = action.get('attributes').get('customer_origin')
                p2 = action.get('attributes').get('customer_dest')
                route = db.get_route(p1, p2)
                dist = route.get('distance')
                h += STARTING_FARE + (dist / 1000) * PRICE_PER_KM
    return h


def evaluate_node(node, db, solution=False):
    # Now if we are evaluating a solution, since it is a node that could not add new actions, we do not need to
    # evaluate the last two actions again; actually the value of the node is already correct, we just have to ensure
    # that it has no h value.
    if solution:
        g = node.benefits - node.costs
        node.value = g
        return g

    # Only evaluate new actions
    action_list = node.actions[-2:]

    benefits = compute_benefits(action_list)
    costs = compute_costs(action_list, node.completed_goals, db)

    node.benefits += benefits
    node.costs += costs

    # Utility (or g value) = benefits - costs
    g = node.benefits - node.costs

    # Calculate heuristic value
    h = 0
    # If the node is a solution, its h value is 0
    if not solution:
        if HEURISTIC:
            h = get_h_value(node, db)

    f_value = g + h
    node.value = f_value
    return f_value


def evaluate_plan(plan, db):
    action_list = [entry.action for entry in plan.entries]

    benefits = compute_benefits(action_list)
    costs = compute_costs(action_list, plan.table_of_goals, db)

    # Utility (or g value) = benefits - costs
    utility = benefits - costs

    return utility
