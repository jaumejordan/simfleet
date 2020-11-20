from math import radians, cos, sin, asin, sqrt

import numpy as np
from loguru import logger
from shapely.geometry import LineString, Point, GeometryCollection


def get_electric_grid(station, power_grids):
    for i in power_grids.keys():
        if station in power_grids[i]['stations']:
            return i


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
        return charge_congestion_function(bound_power_percentage, limit_power, power_consumption, original_cost,
                                          mean_overlap)
    else:
        return original_cost


# bound_power: a partir de quan comença a estar congestionada la xarxa
# limit_power: sumatori del power de les estacions de la xarxa; capacitat màxima de la xarxa (quan peta)
# funció de congestió normal (True, False)
def charge_congestion_function(bound_power_percentage, limit_power, power_consumption, cost, mean_overlap):
    occupation = (power_consumption / limit_power)  # * 100

    if occupation < bound_power_percentage:
        return cost
    else:  # més d'un bound_power_percentage% d'cupació de la xarxa
        # aplicar funció de cost segons (ocupation - bound_power_percentage)
        logger.debug(
            f"Overlaps: {mean_overlap}, power_consumption: {power_consumption}, original_cost: {cost}, "
            f"increment: {((occupation - bound_power_percentage) * cost) * mean_overlap}")
        return cost + ((occupation - bound_power_percentage) * cost) * mean_overlap


def check_road_congestion(a1, db):
    # List to store the intersection percentages with other routes
    res = []
    # Extract a1's time interval
    a1_interval = [a1.get('statistics').get('init'),
                   a1.get('statistics').get('init') + a1.get('statistics').get('time')]

    # Extract a1's route
    a1_route = db.extract_route(a1)
    a1_distance = a1_route.get('distance')

    # Get all non CHARGE type actions which occur in overlapping intervals to action's a1 timespan
    if db.joint_plan.get('joint') is not None:
        for entry in db.joint_plan.get('joint').entries:
            a2 = entry.action
            if a2.get('type') != 'CHARGE':
                a2_interval = [a2.get('statistics').get('init'),
                               a2.get('statistics').get('init') + a2.get('statistics').get('time')]

                if overlap_interval(a1_interval, a2_interval) > 0:
                    # Extract a2's route
                    a2_route = db.extract_route(a2)
                    # Compute route intersection distance
                    intersec_distance = route_intersection_distance(a1_route, a2_route)
                    if intersec_distance > 0:
                        # Compute intersection %
                        intersec_percentage = intersec_distance / a1_distance
                        if intersec_percentage > 1.1:
                            logger.critical(f"Invalid percentage: {intersec_distance } / {a1_distance} = {intersec_percentage}")
                        if intersec_percentage > 1:
                            intersec_percentage = 1

                        res.append(intersec_percentage)

        if len(res) > 0:
            logger.error(f"Route intersected with another {len(res)} routes. Intersection percentages: {res}")


def route_intersection_distance(r1, r2):
    distance = 0
    a = path_to_linestring(r1.get('path'))
    b = path_to_linestring(r2.get('path'))
    x = a.intersection(b)
    logger.warning(f"Intersection is {x}")
    # intersection can be POINT, LINESTRING EMPTY, LINESTRING, MULTILINESTRING or GEOMETRYCOLLECTION
    # if the routes intersect, check how much they do so
    if isinstance(x, GeometryCollection):
        for ob in x:
            # if part of the intersection is a LineString
            if isinstance(ob, LineString):
                # get list of coordinates (path) from LineString
                piece = linestring_to_path(ob)
                # calculate distance between each pair of points according to Harversine formula
                for i in range(0, len(piece) - 1):
                    point1 = piece[i]
                    point2 = piece[i + 1]
                    distance += haversine(point1[0], point1[1], point2[0], point2[1])
            elif isinstance(ob, Point):
                # do nothing
                distance += 0

    return distance


# Turns a list of tuple or list coordinates into a Shapely LineString
def path_to_linestring(path):
    res = []
    for sublist in path:
        res.append((sublist[0], sublist[1]))
    return LineString(res)


# Tuns a Shapely LineString into a list of list coordinates
def linestring_to_path(linestring):
    res = []
    x, y = linestring.coords.xy
    for i in range(0, len(x)):
        res.append([x[i], y[i]])
    return res


# Calculates distance between 2 GPS coordinates
def haversine(lat1, lon1, lat2, lon2):
    """
    Calculate the great circle distance between two points
    on the earth (specified in decimal degrees)
    """
    # convert decimal degrees to radians
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])

    # haversine formula
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * asin(sqrt(a))
    r = 6371000  # 6371 Radius of earth in kilometers. Use 3956 for miles
    return c * r


def overlap_interval(x, y):
    if y[0] < x[0] < y[1] and x[0] < y[1] < x[1]:
        return 1

    elif x[0] < y[0] < x[1] and y[0] < x[1] < y[1]:
        return 2

    elif x[0] > y[0] and x[1] < y[1]:
        return 3

    elif y[0] > x[0] and y[1] < x[1]:
        return 4

    else:
        return 0


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
