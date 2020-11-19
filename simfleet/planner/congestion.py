import numpy as np
from loguru import logger


def get_electric_grid(station, power_grids):
    for i in power_grids.keys():
        if station in power_grids[i]['stations']:
            return i


# electric_grids = {
#     1: [station1, ...]
# }

# station_usage = {
#     station1: [usage1, ...]
# }

# usage1 = {
#     agent: taxi1,
#     station: station1,
#     at_station: 5.50,
#     init_charge: 5.50,
#     end_charge: 11.20,
#     inv: None/INV
#     }

def check_charge_congestion(u1, station, original_cost, db):
    station_usage = db.joint_plan.get('station_usage')
    power_grids = db.joint_plan.get('power_grids')
    # Compare if current usage overlaps with any other usage
    congestion_time = 0
    current_grid = get_electric_grid(station, power_grids)
    limit_power = power_grids.get(current_grid).get('limit_power')
    # TODO extract from database's config file
    bound_power_percentage = 0.5

    # Compare against charges in stations of the same grid
    same_grid_charges = []
    for same_grid_station in power_grids.get(current_grid).get('stations'):
        for usage in station_usage.get(same_grid_station):
            same_grid_charges.append(usage)

    if len(same_grid_charges) == 0:
        return original_cost

    # Save individual congestion percentages
    overlaps = np.ndarray([0])

    power_consumption = u1.get('power')
    congested_agents = 0
    for u2 in same_grid_charges:
        if u2.get('inv') is None and u2.get('agent') != u1.get('agent'):  # you can't overlap with yourself
            ov = overlap(u1, u2)
            if len(ov) > 0:

                power_consumption += u2.get('power')
                congested_agents += 1

                if len(ov) > 1:
                    logger.critical(f"Usages {u1} and {u2} overlap in more than one way: {ov}")
                    exit()
                if ov[0] == 1:
                    congestion_time = u2.get('end_charge') - u1.get('init_charge')
                if ov[0] == 2:
                    congestion_time = u1.get('end_charge') - u2.get('init_charge')
                if ov[0] == 3:
                    congestion_time = u1.get('end_charge') - u1.get('init_charge')
                if ov[0] == 4:
                    congestion_time = u2.get('end_charge') - u2.get('init_charge')

                congestion_percentage = congestion_time / (u1.get('end_charge') - u1.get('init_charge'))
                overlaps = np.append(overlaps, [congestion_percentage])

    mean_overlap = overlaps.mean()
    if congested_agents > 0:
        return charge_congestion_function(bound_power_percentage, limit_power, power_consumption, original_cost, mean_overlap)
    else:
        return original_cost


# bound_power: a partir de quan comença a estar congestionada la xarxa
# limit_power: sumatori del power de les estacions de la xarxa; capacitat màxima de la xarxa (quan peta)
# funció de congestió normal (True, False)
def charge_congestion_function(bound_power_percentage, limit_power, power_consumption, cost, mean_overlap):
    occupation = (power_consumption/limit_power) # * 100

    if occupation < bound_power_percentage:
        return cost
    else: # més d'un bound_power_percentage% d'cupació de la xarxa
        # aplicar funció de cost segons (ocupation - bound_power_percentage)
        logger.debug(
            f"Overlaps: {mean_overlap}, power_consumption: {power_consumption}, original_cost: {cost}, "
            f"increment: {((occupation - bound_power_percentage) * cost) * mean_overlap}")
        return cost + ((occupation - bound_power_percentage) * cost) * mean_overlap


def check_congestion_network(u1, station_usage, electric_grids):
    for grid in electric_grids.keys():
        same_grid_stations = electric_grids.get(grid)
        # Get a list of every charge occurring in the grid
        same_grid_charges = []
        for station in same_grid_stations:
            same_grid_charges += station_usage.get(station)
            for i in range(len(same_grid_charges)):
                u1 = same_grid_charges[i]
                for j in range(i + 1, len(same_grid_charges)):
                    u2 = same_grid_charges[j]


def overlap(u1, u2):
    # u1 starts before u2 finishes
    case1 = u2.get('init_charge') < u1.get('init_charge') < u2.get('end_charge') \
            and u1.get('init_charge') < u2.get('end_charge') < u1.get('end_charge')

    # u2 starts before u1 finishes
    case2 = u1.get('init_charge') < u2.get('init_charge') < u1.get('end_charge') \
            and u2.get('init_charge') < u1.get('end_charge') < u2.get('end_charge')

    # u1 inside u2
    case3 = u1.get('init_charge') > u2.get('init_charge') and u1.get('end_charge') < u2.get('end_charge')
    # u2 inside u1
    case4 = u2.get('init_charge') > u1.get('init_charge') and u2.get('end_charge') < u1.get('end_charge')

    res = []

    if case1:
        # logger.debug(f"Usage nº1 [{u1.get('init_charge')}, {u1.get('end_charge')}] starts before "
        #              f"nº2 [{u2.get('init_charge')}, {u2.get('end_charge')}] finishes")
        res.append(1)
    if case2:
        # logger.debug(f"Usage nº2 [{u2.get('init_charge')}, {u2.get('end_charge')}] starts before "
        #              f"nº1[{u1.get('init_charge')}, {u1.get('end_charge')}] finishes")
        res.append(2)
    if case3:
        # logger.debug(f"Usage nº1 [{u1.get('init_charge')}, {u1.get('end_charge')}] is contained in "
        #              f"nº2 [{u2.get('init_charge')}, {u2.get('end_charge')}]")
        res.append(3)
    if case4:
        # logger.debug(f"Usage nº2 [{u2.get('init_charge')}, {u2.get('end_charge')}] is contained in "
        #              f"nº1 [{u1.get('init_charge')}, {u1.get('end_charge')}]")
        res.append(4)
    return res
