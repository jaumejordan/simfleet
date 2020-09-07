# SPEED = 2000  # km/h
# STARTING_FARE = 10# 1.45
# PRICE_PER_KM = 0 # 1.08 # 0
# PENALTY = 0.1 # 10% of the traveled km
# PRICE_PER_kWh = 0.0615
# GOAL_PERCENTAGE = 1

SPEED = 2000  # km/h
STARTING_FARE = 1.45
PRICE_PER_KM = 1.08  # 0
PENALTY = 0.1  # 10% of the traveled km
PRICE_PER_kWh = 0.0615


# ##Experimentation - problem 1
# CONFIG_FILE = "configs/3-agent-config.json"
# ACTIONS_FILE = "actions/3-agent-config-actions.json"
# ROUTES_FILE = "routes/3-agent-config-routes.json"
# GOAL_PERCENTAGE = 1 # 100%

# Experimentation - problem 2
CONFIG_FILE = "configs/problem2-config.json"
ACTIONS_FILE = "actions/problem2-actions.json"
ROUTES_FILE = "routes/problem2-routes.json"
# 3 taxi, 6 customer, 50% is 3 customers per taxi
GOAL_PERCENTAGE = 1

#  # Experimentation - problem 3
# CONFIG_FILE = "configs/problem3-config.json"
# ACTIONS_FILE = "actions/problem3-actions.json"
# ROUTES_FILE = "routes/problem3-routes.json"
#  # 5 taxi, 10 customer, 40% is 4 customers per taxi
# GOAL_PERCENTAGE = 1

# Experimentation - problem 4
# CONFIG_FILE = "configs/problem4-config.json"
# ACTIONS_FILE = "actions/problem4-actions.json"
# ROUTES_FILE = "routes/problem4-routes.json"
# # 10 taxi, 30 customer, 30% is 9 customers per taxi, 20% is 6 per taxi
# GOAL_PERCENTAGE = 0.3

# Experimentation - problem 5
# CONFIG_FILE = "configs/problem5-config.json"
# ACTIONS_FILE = "actions/problem5-actions.json"
# ROUTES_FILE = "routes/problem5-routes.json"
# 20 taxi, 60 customer, 20% is 12 customers per taxi, 10% is 6 per taxi
# GOAL_PERCENTAGE = 1

# CONFIG_FILE = "configs/10taxi-config.json"
# ACTIONS_FILE = "actions/10config-actions.json"
# ROUTES_FILE = "routes/10config-routes.json"

# CONFIG_FILE = "configs/20-taxi-fsm.json"
# ACTIONS_FILE = "actions/20config-actions.json"
# ROUTES_FILE = "routes/20config-routes.json"

def get_benefit(action):
    return STARTING_FARE + (action.get('statistics').get('dist') / 1000) * PRICE_PER_KM


def get_travel_cost(action):
    return PENALTY * (action.get('statistics').get('dist') / 1000)


def get_charge_cost(action):
    return PRICE_PER_kWh * action.get('statistics').get('need')
