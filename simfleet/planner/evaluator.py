from itertools import permutations
from operator import itemgetter

from loguru import logger

from simfleet.planner.congestion import check_charge_congestion, check_road_congestion
from simfleet.planner.constants import STARTING_FARE, PRICE_PER_KM, TRAVEL_PENALTY, PRICE_PER_kWh, TIME_PENALTY, \
    INVALID_CHARGE_PENALTY, HEURISTIC, STATION_CONGESTION, ROAD_CONGESTION, PRINT_OUTPUT, OLD_HEURISTIC, NEW_HEURISTIC

HEURISTIC_VERBOSE = 0
NO_BENEFITS = True

#############################################################
####################### MAIN FUNCTIONS ######################
#############################################################

def evaluate_node(node, db, solution=False):
    # Now if we are evaluating a solution, since it is a node that could not add new actions, we do not need to
    # evaluate the last two actions again; actually the value of the node is already correct, we just have to ensure
    # that it has no h value.
    if solution:
        if HEURISTIC_VERBOSE > 0:
            logger.info(" ")
            logger.info("Solution node")
            logger.info(f"Node benefits: {node.benefits}")
            logger.info(f"Node costs: {node.costs}")
        g = node.benefits - node.costs
        if HEURISTIC_VERBOSE > 0:
            logger.info(f"G-value: {g}")
        node.value = g
        if HEURISTIC_VERBOSE > 0:
            logger.info(f"F-value: {node.value}")
        return g

    # Only evaluate new actions
    action_list = node.actions[-2:]

    benefits = compute_benefits(action_list)
    costs = compute_costs(action_list, node.completed_goals, db)

    node.benefits += benefits
    node.costs += costs
    if HEURISTIC_VERBOSE > 0:
        logger.info(" ")
        logger.info("Non-solution node")
        logger.info(f"Node benefits: {node.benefits}")
        logger.info(f"Node costs: {node.costs}")

    # Utility (or g value) = benefits - costs
    g = node.benefits - node.costs
    if HEURISTIC_VERBOSE > 0:
        logger.info(f"G-value: {g}")

    # Calculate heuristic value
    h = 0
    # If the node is a solution, its h value is 0
    if not solution:
        if HEURISTIC:
            if OLD_HEURISTIC:
                h = get_h_value(node, db)
            elif NEW_HEURISTIC:
                h = best_permutation_heuristic(node, db)
    if HEURISTIC_VERBOSE > 0:
        logger.info(f"H-value: {h}")

    f_value = g + h
    node.value = f_value
    if HEURISTIC_VERBOSE > 0:
        logger.info(f"F-value: {node.value}")
    return f_value


def evaluate_plan(plan, db):
    action_list = [entry.action for entry in plan.entries]

    benefits = compute_benefits(action_list)
    costs = compute_costs(action_list, plan.table_of_goals, db)

    # Utility (or g value) = benefits - costs
    utility = benefits - costs

    return utility


#############################################################
#################### HEURISTIC FUNCTIONS ####################
#############################################################

def get_h_value(node, db):
    benefits = 0
    costs = 0
    agent_id = node.actions[0].get('agent')

    # Get a list with the non-served customers
    non_served_customers = [x for x in node.agent_goals if x not in node.already_served()]

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

    if NO_BENEFITS:
        h = 0 - costs
    else:
        h = benefits - costs
    return h


def best_permutation_heuristic(node, db):
    # Check if there are customers left to serve
    non_served_customers = [x for x in node.agent_goals if x not in node.already_served()]
    if len(non_served_customers) == 0:
        return 0

    # Generate dictionary key
    agent = node.actions[0].get('agent')
    served_customers = node.already_served()
    position = node.agent_pos
    key = str(position) + str(served_customers) + str(non_served_customers)

    if HEURISTIC_VERBOSE > 0:
        logger.debug(" ")
        logger.debug("Looking for best permutation...")
        logger.debug(f"Key is {key}")

    # If the best order for that situation is already calculated
    if db.optimal_orders.get(agent).get(key) is not None:
        return db.optimal_orders.get(agent).get(key)[0]
    else:
        # Calculate best order and the reported utility
        time = node.end_time

        # If there is only one customer left to serve it has no sense to calculate all possible permutations
        if len(non_served_customers) == 1:
            order = non_served_customers[:]
            optimal_permutation = (get_order_utility(agent, position, time, order, db),
                                   non_served_customers[0])
        else:
            optimal_permutation = get_optimal_permutation(agent, position, time, non_served_customers, db)

        db.optimal_orders[agent][key] = optimal_permutation
        return optimal_permutation[0]


def get_optimal_permutation(agent, position, time, customers, db):
    ranking = []
    # Get all permutations of customers
    permut = get_all_permutations(customers)
    if HEURISTIC_VERBOSE > 0:
        logger.debug(f"Permutations: {permut}")

    # Calculate utility of a particular permutation and store it in the ranking list
    for order in permut:
        order_list = list(order)
        if len(order) == 0:
            value = 0
        else:
            value = get_order_utility(agent, position, time, order_list, db)
        ranking.append((value, order))
    if HEURISTIC_VERBOSE > 0:
        logger.debug(f"Ranking: {ranking}")

    # Get best permutation together with its value from ranking list
    best_order = max(ranking, key=itemgetter(0))  # tuple[0] = value, tuple[1] = order
    if HEURISTIC_VERBOSE > 0:
        logger.debug(f"Best order is {best_order}")

    return best_order


# Given a list of elements, returns every possible ordering of its elements
def get_all_permutations(list_of_elems):
    return list(permutations(list_of_elems))


# Given a list of customers in a certain order, returns the utility obtained from serving
# all customers in the determined order
def get_order_utility(agent, position, time, order, db):
    costs = 0
    benefits = 0
    current_pos = position
    current_time = time
    while len(order) > 0:
        # Extract next customer
        customer = order.pop(0)
        # Get customer actions
        action1, action2 = db.get_customer_couple(agent, customer)
        action1 = db.fill_statistics(action1, current_pos=current_pos, current_time=current_time)
        action2 = db.fill_statistics(action2, current_time=current_time)
        # Compute costs
        pick_up_time = current_time + action1.get('statistics').get('time')
        waiting_time_cost = pick_up_time * TIME_PENALTY
        travel_cost = get_travel_cost(action1) + get_travel_cost(action2)
        costs += waiting_time_cost + travel_cost
        # costs += travel_cost
        # Compute benefit
        benefits += get_benefit(action2) + 1000
        # Update position and time
        current_pos = action2.get('attributes').get('customer_dest')
        current_time += (action1.get('statistics').get('time') + action2.get('statistics').get('time'))
    if NO_BENEFITS:
        return 0 - costs
    return benefits - costs



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


#############################################################
################# BENEFITS & COSTS FUNCTIONS ################
#############################################################

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
    if NO_BENEFITS:
        return 0
    return benefits


# Action_list must be node.actions or plan.entries
# table of goals must be list of tuples or dictionary
def compute_costs(action_list, table_of_goals, db):
    # New: only print warning when evaluating (or reevaluating) a plan, not a node
    # Evaluating a node
    is_node = False
    if isinstance(table_of_goals, list):
        is_node = True

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
                    if not is_node:
                        if PRINT_OUTPUT > 0:
                            logger.warning(
                                f"Travel cost incremented by congestion from {travel_cost} to {road_congestion}")
                else:
                    costs += travel_cost
            else:
                costs += travel_cost

        # For actions that entail charging, pay for the charged electricity
        else:
            charge_cost = get_charge_cost(action)
            if action.get('inv') == 'INV':
                costs += INVALID_CHARGE_PENALTY
            else:
                if STATION_CONGESTION:
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
                    charge_congestion = check_charge_congestion(usage, station, charge_cost, db)

                    if charge_cost != charge_congestion:
                        if not is_node:
                            if PRINT_OUTPUT > 0:
                                logger.warning(
                                    f"Charging cost incremented by congestion from {charge_cost} to {charge_congestion}")
                        costs += charge_congestion
                    else:
                        costs += charge_cost
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
