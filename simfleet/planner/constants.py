# SPEED = 2000  # km/h
# STARTING_FARE = 10# 1.45
# PRICE_PER_KM = 0 # 1.08 # 0
# PENALTY = 0 # 10% of the traveled km
# PRICE_PER_kWh = 0.0615

SPEED = 2000  # km/h
STARTING_FARE = 1.45
PRICE_PER_KM = 1.08  # 0
PENALTY = 0.1  # 10% of the traveled km
PRICE_PER_kWh = 0.0615

CONFIG_FILE = "3_planner_config.json"
ACTIONS_FILE = "test-actions.json"
ROUTES_FILE = "all-routes.json"


def get_benefit(action):
    return STARTING_FARE + (action.get('statistics').get('dist') / 1000) * PRICE_PER_KM


def get_travel_cost(action):
    return PENALTY * (action.get('statistics').get('dist') / 1000)


def get_charge_cost(action):
    return PRICE_PER_kWh * action.get('statistics').get('need')
