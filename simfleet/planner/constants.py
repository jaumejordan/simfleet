# SPEED = 2000  # km/h
# STARTING_FARE = 10# 1.45
# PRICE_PER_KM = 0 # 1.08 # 0
# PENALTY = 0.1 # 10% of the traveled km
# PRICE_PER_kWh = 0.0615
# GOAL_PERCENTAGE = 1
PRINT_OUTPUT = 1

SPEED = 2000  # km/h
STARTING_FARE = 5
PRICE_PER_KM = 1.08  # 0
TRAVEL_PENALTY = 0  # 10% of the traveled km
PRICE_PER_KWH = 0.3
POWER_CONSUMPTION_PER_KM = 0.14
POWER_PRICE_PER_KM = PRICE_PER_KWH*POWER_CONSUMPTION_PER_KM
TIME_PENALTY = 1
# MAX_STATION_DIST = 10000 # maximum distance to a station to consider it a place to charge
RADIUS = 5000
INVALID_CHARGE_PENALTY = 10000  # invalid charge actions have its cost multiplied 100 times to discorage agents to keep
# proposing them

# Search / BR speedups
HEURISTIC = True
OLD_HEURISTIC = False
NEW_HEURISTIC = not OLD_HEURISTIC
INITIAL_GREEDY_PLAN = True

# Congestions
STATION_CONGESTION = True
ROAD_CONGESTION = True

# Memory management
RELOAD_ACTIONS = False
DEEPCOPY = not RELOAD_ACTIONS

# Congestion bound variables
BOUND_POWER_PERCENTAGE = 0.5
BOUND_ROUTE_PERCENTAGE = 0.3

# # Congestion test 1
# CONFIG_FILE = "configs/congestion1.json"
# ACTIONS_FILE = "actions/congestion1-actions.json"
# ROUTES_FILE = "routes/congestion-routes.json"

# # Congestion test 2
# CONFIG_FILE = "configs/congestion2.json"
# ACTIONS_FILE = "actions/congestion2-actions.json"
# ROUTES_FILE = "routes/congestion-routes.json"

# # Test heuristica
# CONFIG_FILE = "configs/problem-test.json"
# ACTIONS_FILE = "actions/problem-test-actions.json"
# ROUTES_FILE = "routes/problem3-routes.json"

# ##Experimentation - problem 1
# CONFIG_FILE = "configs/3-agent-config.json"
# ACTIONS_FILE = "actions/3-agent-config-actions.json"
# ROUTES_FILE = "routes/3-agent-config-routes.json"

# # Experimentation - problem 2
# CONFIG_FILE = "configs/problem2-config.json"
# ACTIONS_FILE = "actions/problem2-actions.json"
# ROUTES_FILE = "routes/problem2-routes.json"
# # 3 taxi, 6 customer, 50% is 3 customers per taxi

# # Experimentation - problem 3
# CONFIG_FILE = "configs/problem3-config.json"
# ACTIONS_FILE = "actions/problem3-actions.json"
# ROUTES_FILE = "routes/problem3-routes.json"
# # 5 taxi, 10 customer, 40% is 4 customers per taxi


# # Experimentation - problem 4
# CONFIG_FILE = "configs/problem4-config.json"
# ACTIONS_FILE = "actions/problem4-actions.json"
# ROUTES_FILE = "routes/problem4-routes.json"
# # 10 taxi, 30 customer, 30% is 9 customers per taxi, 20% is 6 per taxi


# #  # Experimentation - problem 5
# CONFIG_FILE = "configs/problem5-config.json"
# ACTIONS_FILE = "actions/problem5-actions.json"
# ROUTES_FILE = "routes/problem5-routes.json"
#  # 20 taxi, 60 customer, 20% is 12 customers per taxi, 10% is 6 per taxi

# Experimentation - 20 taxi, 60 customer, 32 stations (genetic)
# 4 rondes, 150 segons
# CONFIG_FILE = "configs/20taxi-60customer-32stations-config.json"
# ACTIONS_FILE = "actions/20taxi-60customer-32stations-actions.json"
# ROUTES_FILE = "routes/50taxi-200customer-32stations-routes.json"

#  # Experimentation - 50 taxi, 150 customer, 16 stations (genetic)
# # 7 rondes, 2048 segons
# CONFIG_FILE = "configs/50taxi-150customer-16stations-config.json"
# ACTIONS_FILE = "actions/50taxi-150customer-16stations-actions.json"
# ROUTES_FILE = "routes/50taxi-200customer-32stations-routes.json"
#
# # Experimentation - 50 taxi, 150 customer, 32 stations (genetic)
# # Converges in 4 BR turns in aprox 600s (3.76s avg planning)
# CONFIG_FILE = "configs/50taxi-150customer-32stations-config.json"
# ACTIONS_FILE = "actions/50taxi-200customer-32stations-actions.json"
# ROUTES_FILE = "routes/50taxi-200customer-32stations-routes.json"

# # Experimentation - 50 taxi, 200 customer, 32 stations (genetic)
# CONFIG_FILE = "configs/50taxi-200customer-32stations-config.json"
# ACTIONS_FILE = "actions/50taxi-200customer-32stations-actions.json"
# ROUTES_FILE = "routes/50taxi-200customer-32stations-routes.json"

# # Experimentation - 100 taxi, 200 customer, 20 stations (uniform)
# CONFIG_FILE = "configs/100taxi-200customer-20stations-config.json"
# ACTIONS_FILE = "actions/100taxi-200customer-20stations-actions.json"
# ROUTES_FILE = "routes/100taxi-200customer-20stations-routes.json"

# # Experimentation - 100 taxi, 300 customer, 20 stations (uniform)
# CONFIG_FILE = "configs/100taxi-300customer-20stations-config.json"
# ACTIONS_FILE = "actions/100taxi-300customer-20stations-actions.json"
# ROUTES_FILE = "routes/100taxi-300customer-20stations-routes.json"

# # Experimentation - 200 taxi, 400 customer, 20 stations (uniform)
# CONFIG_FILE = "configs/200taxi-400customer-20stations-config.json"
# ACTIONS_FILE = "actions/200taxi-400customer-20stations-actions.json"
# ROUTES_FILE = "routes/200taxi-400customer-20stations-routes.json"

CONFIG_FILE = "configs/20taxi-60customer.json"
ACTIONS_FILE = "actions/20taxi-60customer.json"
ROUTES_FILE = "routes/20taxi-60customer.json"

# CONFIG_FILE = "configs/20taxi-80customer.json"
# ACTIONS_FILE = "actions/20taxi-80customer.json"
# ROUTES_FILE = "routes/20taxi-80customer.json"

# CONFIG_FILE = "configs/50taxi-250customer.json"
# ACTIONS_FILE = "actions/50taxi-250customer.json"
# ROUTES_FILE = "routes/50taxi-250customer.json"
#
