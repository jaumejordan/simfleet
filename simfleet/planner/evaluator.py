from simfleet.planner.constants import STARTING_FARE, PRICE_PER_KM, TRAVEL_PENALTY, PRICE_PER_kWh, TIME_PENALTY, \
    INVALID_CHARGE_PENALTY, HEURISTIC
from loguru import logger


def get_benefit(action):
    return STARTING_FARE + (action.get('statistics').get('dist') / 1000) * PRICE_PER_KM


def get_travel_cost(action):
    return TRAVEL_PENALTY * (action.get('statistics').get('dist') / 1000)


def get_charge_cost(action):
    return PRICE_PER_kWh * action.get('statistics').get('need')


# Returns the f value of a node
def evaluate_node(self, node, solution=False):
    # Calculate g value w.r.t Joint plan + node actions
    # taking into account charging congestions (implementar a futur)

    # Benefits
    benefits = 0
    for action in node.actions:
        if action.get('type') == 'MOVE-TO-DEST':
            benefits += get_benefit(action) + 1000
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
            if action.get('inv') == 'INV':
                costs *= INVALID_CHARGE_PENALTY

        if action.get('type') == 'PICK-UP':
            customer = action.get('attributes').get('customer_id')
            for tup in node.completed_goals:
                if tup[0] == customer:
                    pick_up = tup
                    break

            # Add waiting time to costs
            costs += pick_up[1] * TIME_PENALTY

    # Utility (or g value) = benefits - costs
    g = benefits - costs

    # Calculate h value w.r.t Table of Goals + node end time
    h = 0
    # If the node is a solution, its h value is 0
    if not solution:
        if HEURISTIC:
            h = self.get_h_value(node)

    f_value = g + h
    node.value = f_value
    return f_value


# Calculates the utility of an individual plan w.r.t. the actions and goals in the Joint plan
def evaluate_plan(self, plan, joint_plan, initial_plan=False):
    # Benefits
    benefits = 0
    for entry in plan.entries:
        action = entry.action
        if action.get('type') == 'MOVE-TO-DEST':
            # CHECK IF I'M THE FIRST ONE PICKING THAT CUSTOMER UP
            plan_owner = action.get('agent')
            customer = action.get('attributes').get('customer_id')
            tup = self.joint_plan.get('table_of_goals').get(customer)
            # if no one is serving the transport
            if tup[0] is None and initial_plan:
                # only accept this as valid when evaluating the initial plans proposed by feasible_joint_plan()
                # since they have to be evaluated before updating the joint plan
                benefits += get_benefit(action) + 1000
            else:
                serving_transport = tup[0]
                if serving_transport == plan_owner:
                    benefits += get_benefit(action) + 1000
    # Costs
    costs = 0
    for entry in plan.entries:
        action = entry.action
        # For actions that entail a movement, pay a penalty per km (10%)
        if action.get('type') != 'CHARGE':
            costs += get_travel_cost(action)
        # For actions that entail charging, pay for the charged electricity
        # TODO price increase if congestion (implementar a futur)
        else:
            costs += get_charge_cost(action)
            if action.get('inv') == 'INV':
                costs *= INVALID_CHARGE_PENALTY

        if action.get('type') == 'PICK-UP':
            customer = action.get('attributes').get('customer_id')
            pick_up = self.joint_plan.get('table_of_goals').get(customer)

            # Double check that the customer is being picked up by the agent
            if pick_up[0] != action.get('agent'):
                logger.critical(f"Agent {action.get('agent')} is being penalized for picking-up customer {customer}"
                                f"when in the ToG it is being picked up as: {pick_up}")
            # Add waiting time to costs
            costs += pick_up[1] * TIME_PENALTY

    # Utility (or g value) = benefits - costs
    utility = benefits - costs

    # if utility < 0:
    #    logger.error("THE COSTS ARE HIGHER THAN THE BENEFITS")

    return utility


def compute_benefits(action_list):
    benefits = 0
    for action in action_list:
        if action.get('type') == 'MOVE-TO-DEST':
            benefits += get_benefit(action) + 1000
    return benefits


# Action_list must be node.actions or plan.entries
# table of goals must be list of tuples or dictionary
def compute_costs(action_list, table_of_goals):
    costs = 0
    for action in action_list:
        # For actions that entail a movement, pay a penalty per km (10%)
        if action.get('type') != 'CHARGE':
            costs += get_travel_cost(action)

        # For actions that entail charging, pay for the charged electricity
        else:
            costs += get_charge_cost(action)
            if action.get('inv') == 'INV':
                costs *= INVALID_CHARGE_PENALTY

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
            costs += pick_up[1] * TIME_PENALTY
    return costs


# Assume the agent can pick up every remaining agent without charging costs
def get_h_value(node):
    return -1


def evaluate_node_2(node, solution=False):
    benefits = compute_benefits(node.actions)
    costs = compute_costs(node.actions, node.completed_goals)

    # Utility (or g value) = benefits - costs
    g = benefits - costs

    # Calculate heuristic value
    h = 0
    # If the node is a solution, its h value is 0
    if not solution:
        if HEURISTIC:
            h = get_h_value(node)

    f_value = g + h
    node.value = f_value
    return f_value


def evaluate_plan_2(plan, joint_plan):
    action_list = [entry.action for entry in plan.entries]

    benefits = compute_benefits(action_list)
    costs = compute_costs(action_list, joint_plan.get('table_of_goals'))

    # Utility (or g value) = benefits - costs
    utility = benefits - costs

    return utility
