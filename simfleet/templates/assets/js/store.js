Vue.use(Vuex);

export const store = new Vuex.Store({
    state: {
        transports: [],
        customers: [],
        stations: [],
        paths: [],
        waiting_time: 0,
        total_time: 0,
        simulation_status: false,
        treedata: {}
    },
    mutations: {
        addTransports: (state, payload) => {
            if (payload.length > 0) {
                let new_paths = [];
                for (let i = 0; i < payload.length; i++) {
                    update_item_in_collection(state.transports, payload[i], transport_popup);

                    if (payload[i].path) {
                        new_paths.push({latlngs: payload[i].path, color: get_color(payload[i].status)})
                    }
                }
                state.paths = new_paths;
            } else {
                state.transports = [];
                state.paths = [];
            }
        },
        addCustomers: (state, payload) => {
            if (payload.length > 0) {
                let new_paths = [];
                for (let i = 0; i < payload.length; i++) {
                    update_item_in_collection(state.customers, payload[i], customer_popup);

                    if (payload[i].path) {
                        new_paths.push({latlngs: payload[i].path, color: get_color(payload[i].status)})
                    }
                }
                state.paths = new_paths;
            } else {
                state.customers = [];
                state.paths = [];
            }
        },
        addStations: (state, payload) => {
            if (payload.length >0) {
                for (let i = 0; i < payload.length; i++) {
                    update_station_in_collection(state.stations, payload[i], station_popup);
                }
            } else {
                state.stations = [];
            }
        },
        update_simulation_status: (state, stats) => {
            if (!stats.is_running) state.simulation_status = false;
            else {
                state.simulation_status = !stats.finished;
            }
        },
        update_tree: (state, payload) => {
            state.treedata = payload;
        }
    },
    getters: {
        get_transports: (state) => {
            return state.transports;
        },
        get_customers: (state) => {
            return state.customers;
        },
        get_stations: (state) => {
            return state.stations;
        },
        get_paths: (state) => {
            return state.paths;
        },
        get_waiting_time: (state) => {
            return state.waiting_time;
        },
        get_total_time: (state) => {
            return state.total_time;
        },
        status: (state) => {
            return state.simulation_status && (state.customers.length || state.transports.length);
        },
        tree: (state) => {
            return state.treedata;
        }
    }
});

let update_item_in_collection = function (collection, item, get_popup) {
    let p = getitem(collection, item);
    if (p === false) {
        item.latlng = L.latLng(item.position[0], item.position[1]);
        item.popup = get_popup(item);
        item.visible = true;
        item.icon_url = item.icon;
        if(item.icon) {
            item.icon = L.icon({iconUrl: item.icon, iconSize: [38, 55]});
        }
        else {
            //item.icon = L.icon({iconUrl: "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7",
            //    iconSize: [38, 55]});
            item.icon = L.icon({iconUrl: item.icon, iconSize: [38, 55]});
            // customer icon hardcoded "data:image/svg+xml;utf8;base64,PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iaXNvLTg4NTktMSI/Pgo8IS0tIEdlbmVyYXRvcjogQWRvYmUgSWxsdXN0cmF0b3IgMTkuMC4wLCBTVkcgRXhwb3J0IFBsdWctSW4gLiBTVkcgVmVyc2lvbjogNi4wMCBCdWlsZCAwKSAgLS0+CjxzdmcgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIiB4bWxuczp4bGluaz0iaHR0cDovL3d3dy53My5vcmcvMTk5OS94bGluayIgdmVyc2lvbj0iMS4xIiBpZD0iQ2FwYV8xIiB4PSIwcHgiIHk9IjBweCIgdmlld0JveD0iMCAwIDUxMi4wMDIgNTEyLjAwMiIgc3R5bGU9ImVuYWJsZS1iYWNrZ3JvdW5kOm5ldyAwIDAgNTEyLjAwMiA1MTIuMDAyOyIgeG1sOnNwYWNlPSJwcmVzZXJ2ZSIgd2lkdGg9IjUxMnB4IiBoZWlnaHQ9IjUxMnB4Ij4KPHBhdGggc3R5bGU9ImZpbGw6I0ZFREFDNjsiIGQ9Ik0zNDkuNzI2LDE1My4zNjloLTguNTJ2NTEuMTIyaDguNTJjMTQuMTE4LDAsMjUuNTYxLTExLjQ0MywyNS41NjEtMjUuNTYxICBTMzYzLjgzNSwxNTMuMzY5LDM0OS43MjYsMTUzLjM2OXoiLz4KPHBhdGggc3R5bGU9ImZpbGw6I0Y1QzRCMDsiIGQ9Ik0xMzYuNzE1LDE3OC45MzFjMCwxNC4xMTgsMTEuNDQzLDI1LjU2MSwyNS41NjEsMjUuNTYxaDguNTJ2LTUxLjEyMmgtOC41MiAgQzE0OC4xNTgsMTUzLjM2OSwxMzYuNzE1LDE2NC44MTIsMTM2LjcxNSwxNzguOTMxeiIvPgo8cGF0aCBzdHlsZT0iZmlsbDojRkVDQjY2OyIgZD0iTTM0OS43MjYsMTUzLjM2OWwxMC4wNTQtNTEuNzE5YzMuMjk3LTE5LjYzMS05Ljk1Mi0zOC4yMTQtMjkuNTgzLTQxLjUxMSAgYy0xLjk5NC0wLjMzMi00LjAxMy0wLjQ5NC02LjAzMi0wLjQ5NGwwLDBjLTUuMDk1LTE1LjI1Mi0xOS4zNjctMjUuNTQ0LTM1LjQ0NS0yNS41NjFIMTg3LjgzOEwxNzAuNzk3LDguNTIybC04LjUyLDguNTIgIGMtMjMuNTI1LDIzLjUyNS0yMy41MzMsNjEuNjYyLTAuMDE3LDg1LjE4N2MwLjAwOSwwLjAwOSwwLjAwOSwwLjAxNywwLjAxNywwLjAxN2gxNTMuMzY3TDM0OS43MjYsMTUzLjM2OXoiLz4KPHBhdGggc3R5bGU9ImZpbGw6I0RCREJEQjsiIGQ9Ik0zNzUuNzk4LDM0OS45MzVsLTYxLjc3My04LjUyTDI1Ni4wMDEsMzc0LjlsLTU4LjAyNC0zMy4xNDRsLTYxLjc3Myw4LjUyICBjLTMzLjcyNCw0LjUwNy01OC45NjEsMzMuMTk2LTU5LjEzMiw2Ny4yMjZ2OTMuNzI1SDQzNC45M3YtOTMuNzI1QzQzNC45MywzODMuMzUyLDQwOS42NSwzNTQuNDYsMzc1Ljc5OCwzNDkuOTM1eiIvPgo8cG9seWdvbiBzdHlsZT0iZmlsbDojRkVEQUM2OyIgcG9pbnRzPSIzMTQuMDI1LDM0MS43NTYgMzA3LjEyMywzNDAuODE4IDMwNy4xMjMsMjgxLjE3NiAyMDQuODc5LDI4MS4xNzYgMjA0Ljg3OSwzNDAuODE4ICAgMTk3Ljk3NywzNDEuNzU2IDI1Ni4wMDEsMzc0LjkgIi8+CjxnPgoJPHBvbHlnb24gc3R5bGU9ImZpbGw6I0VBRUFFQTsiIHBvaW50cz0iMjA0Ljg3OSw0MDguOTgyIDI1Ni4wMDEsMzc0LjkgMjA0Ljg3OSwzNDAuODE4IDE4Ny44MzgsMzQwLjgxOCAgIi8+Cgk8cG9seWdvbiBzdHlsZT0iZmlsbDojRUFFQUVBOyIgcG9pbnRzPSIyNTYuMDAxLDM3NC45IDMwNy4xMjMsNDA4Ljk4MiAzMjQuMTY0LDM0MC44MTggMzA3LjEyMywzNDAuODE4ICAiLz4KPC9nPgo8cG9seWxpbmUgc3R5bGU9ImZpbGw6IzJFNkFBMzsiIHBvaW50cz0iMjMwLjQ0LDUxMS4yMjcgMjM4Ljk2LDQxNy41MDIgMjMwLjQ0LDM5MS45NDEgMjU2LjAwMSwzNzQuOSAyODEuNTYyLDM5MS45NDEgICAyNzMuMDQyLDQxNy41MDIgMjgxLjU2Miw1MTEuMjI3ICIvPgo8cGF0aCBzdHlsZT0iZmlsbDojRjVDNEIwOyIgZD0iTTMwNy4xMjMsMzI4LjM3OXYtNDcuMjAzSDIwNC44Nzl2NDcuMjAzQzI0My4yMiwzNDQuOTkzLDI2OC43ODIsMzQ0Ljk5MywzMDcuMTIzLDMyOC4zNzl6Ii8+CjxwYXRoIHN0eWxlPSJmaWxsOiNCRkJGQkY7IiBkPSJNNzcuMDcyLDQxNy41MDJ2OTMuNzI1aDM0LjA4MlYzNTguNTQxQzkwLjA4MywzNzAuNzA4LDc3LjA4OSwzOTMuMTc2LDc3LjA3Miw0MTcuNTAyeiIvPgo8cGF0aCBzdHlsZT0iZmlsbDojRkVEQUM2OyIgZD0iTTM0OS43MjYsMTUzLjM2OXY0OC41NjZjLTAuMDA5LDI0LjAzNi02LjEzNSw0Ny42NjMtMTcuODA4LDY4LjY3NWwwLDAgIGMtMTUuMzIsMjcuNTY0LTQ0LjM4Myw0NC42NTUtNzUuOTE3LDQ0LjY0N2wwLDBjLTMxLjUzNCwwLjAwOS02MC41OTctMTcuMDgzLTc1LjkxNy00NC42NDdsMCwwICBjLTExLjY3My0yMS4wMTEtMTcuNzk5LTQ0LjYzOC0xNy44MDgtNjguNjc1di05OS42ODloMTUzLjM2N0wzNDkuNzI2LDE1My4zNjl6Ii8+CjxwYXRoIHN0eWxlPSJmaWxsOiNGNUM0QjA7IiBkPSJNMTk2LjM1OCwxMDIuMjQ3aC0zNC4wODJ2OTkuNjg5YzAuMDA5LDI0LjAzNiw2LjEzNSw0Ny42NjMsMTcuODA4LDY4LjY3NSAgYzguNTIsMTUuMjUyLDIxLjQ4LDI3LjU1NSwzNy4xNDksMzUuMjc1QzE4Ny44MzgsMjIxLjUzMywxOTYuMzU4LDEwMi4yNDcsMTk2LjM1OCwxMDIuMjQ3eiIvPgo8cGF0aCBzdHlsZT0iZmlsbDojRjVBRDc2OyIgZD0iTTE0Ni40MjksNDUuMzMxYy01LjA2MSwyMC40NCwwLjk1NCw0Mi4wMzEsMTUuODQ4LDU2LjkxNmgxMzYuMzI3ICBDMjAxLjgxMSwxMDIuMjQ3LDE2Mi4yNzYsNjguMTY1LDE0Ni40MjksNDUuMzMxeiIvPgo8cGF0aCBkPSJNMzQ5LjcyNiwyMTMuMDEyaC04LjUydi0xNy4wNDFoOC41MmM5LjM5OCwwLDE3LjA0MS03LjY0MywxNy4wNDEtMTcuMDQxYzAtOS4zOTgtNy42NDMtMTcuMDQxLTE3LjA0MS0xNy4wNDFoLTguNTJ2LTE3LjA0MSAgaDguNTJjMTguNzk2LDAsMzQuMDgyLDE1LjI4NiwzNC4wODIsMzQuMDgyUzM2OC41MjIsMjEzLjAxMiwzNDkuNzI2LDIxMy4wMTJ6Ii8+CjxwYXRoIGQ9Ik0xNzAuNzk3LDIxMy4wMTJoLTguNTJjLTE4Ljc5NiwwLTM0LjA4Mi0xNS4yODYtMzQuMDgyLTM0LjA4MnMxNS4yODYtMzQuMDgyLDM0LjA4Mi0zNC4wODJoOC41MnYxNy4wNDFoLTguNTIgIGMtOS4zOTgsMC0xNy4wNDEsNy42NDMtMTcuMDQxLDE3LjA0MWMwLDkuMzk4LDcuNjQzLDE3LjA0MSwxNy4wNDEsMTcuMDQxaDguNTJWMjEzLjAxMnoiLz4KPHBhdGggZD0iTTI2NC41MjEsMjMwLjA1M0gyMzguOTZjLTIuNjc1LDAtNS4xODktMS4yNTMtNi43OTktMy4zOTFjLTEuNjEtMi4xMzktMi4xMy00Ljg5OS0xLjM4OS03LjQ3MmwxNy4wNDEtNTkuNjQzbDE2LjM4NSw0LjY4NiAgbC0xMy45NDgsNDguNzc5aDE0LjI2M3YxNy4wNDFIMjY0LjUyMXoiLz4KPHBhdGggZD0iTTI1Ni4wMTgsMzIzLjc3OGMtMC4wMTcsMC0wLjAzNCwwLTAuMDUxLDBjLTM0LjU5MywwLTY2LjUyNy0xOC43NzktODMuMzM4LTQ5LjAzNSAgYy0xMi4zNDYtMjIuMjEzLTE4Ljg3My00Ny4zOTEtMTguODgxLTcyLjc5OHYtOTkuNjk3YzAtNC43MDMsMy44MTctOC41Miw4LjUyLTguNTJoMTUzLjM2N2MyLjg0NiwwLDUuNTA0LDEuNDIzLDcuMDg5LDMuNzkyICBsMzQuMDgyLDUxLjEyMmMwLjkyOSwxLjM5NywxLjQzMSwzLjA0MiwxLjQzMSw0LjcyOXY0OC41NjZjLTAuMDA5LDI1LjQwOC02LjU0NCw1MC41ODYtMTguODgxLDcyLjgwNyAgQzMyMi41NTQsMzA0Ljk5LDI5MC42MTksMzIzLjc3OCwyNTYuMDE4LDMyMy43Nzh6IE0yNTUuOTkyLDMwNi43MzdjMC4wMDgsMCwwLjAxNywwLDAuMDE3LDBjMjguNDI0LDAsNTQuNjUtMTUuNDMsNjguNDUzLTQwLjI2NyAgYzEwLjk0LTE5LjY5OSwxNi43MjYtNDIuMDE0LDE2LjczNC02NC41NDJ2LTQ1Ljk4NWwtMzAuMTItNDUuMTc1aC0xNDAuMjh2OTEuMTY4YzAuMDA5LDIyLjUyOCw1Ljc5NCw0NC44NDMsMTYuNzM0LDY0LjUzNCAgYzEzLjgwMywyNC44NDYsNDAuMDI5LDQwLjI2Nyw2OC40NDQsNDAuMjY3QzI1NS45ODQsMzA2LjczNywyNTUuOTkyLDMwNi43MzcsMjU1Ljk5MiwzMDYuNzM3eiIvPgo8cGF0aCBkPSJNMjQ4LjkyOSwyNjQuMTM1aC05Ljk2OXYtMTcuMDQxaDkuOTY5YzEzLjI2Ni0wLjAwOSwyNS43NC01LjE3MiwzNS4xMy0xNC41NTNsMTIuMDQ4LDEyLjA1NiAgQzI4My40OTYsMjU3LjE5MSwyNjYuNzQ1LDI2NC4xMjYsMjQ4LjkyOSwyNjQuMTM1eiIvPgo8Y2lyY2xlIGN4PSIyMDQuOTEzIiBjeT0iMTcwLjQxIiByPSIxNy4wNDEiLz4KPGNpcmNsZSBjeD0iMzA3LjE1OCIgY3k9IjE3MC40MSIgcj0iMTcuMDQxIi8+CjxwYXRoIGQ9Ik0zNTguMTI3LDE2My4yOTZsLTE2LjgxMS0yLjgwM2wxMC4wNTQtNjAuMjM5YzEuMjE4LTcuMjU5LTAuNDYtMTQuNTUzLTQuNzI5LTIwLjUzNCAgYy00LjI2OS01Ljk4MS0xMC42MDgtOS45NTItMTcuODU5LTExLjE3Yy0xLjUxNy0wLjI1Ni0zLjIzOC0wLjQ0My00LjYxLTAuMzc1Yy0wLjAwOSwwLTAuMDA5LDAtMC4wMTcsMCAgYy0zLjY2NCwwLTYuOTI3LTIuMzQzLTguMDc3LTUuODE5Yy0zLjk0NS0xMS44MDEtMTQuOTQ1LTE5LjczMy0yNy4zNzYtMTkuNzVIMTg3LjgzOGMtMi44NDYsMC01LjUwNC0xLjQyMy03LjA4OS0zLjc5MiAgbC0xMS4yODEtMTYuOTEzbC0xLjE3NiwxLjE2N2MtOS43NjQsOS43NjQtMTUuMTQ5LDIyLjc1OC0xNS4xNDksMzYuNTdjMCwxMy44Miw1LjM3NiwyNi44MDUsMTUuMTQxLDM2LjU3bC0xMi4wMzksMTIuMDY1ICBjLTI2LjgxNC0yNi44MjItMjYuODE0LTcwLjQ0NywwLTk3LjI1Mmw4LjUyLTguNTJjMS44MDYtMS43OTgsNC4zMjgtMi43MTgsNi44NjctMi40NTRjMi41MzksMC4yNDcsNC44MzEsMS42MjcsNi4yNDUsMy43NDkgIGwxNC41MTksMjEuNzdoOTYuMzIzYzE3Ljc5OSwwLjAxNywzMy43NDEsMTAuMjMzLDQxLjMyNCwyNS45MzZjMC41MjgsMC4wNjgsMS4wMzksMC4xNDUsMS41NjgsMC4yMyAgYzExLjc1LDEuOTY4LDIyLjAxNyw4LjM5MywyOC45MjcsMTguMDg5czkuNjI4LDIxLjQ5Nyw3LjY1MSwzMy4yMzhMMzU4LjEyNywxNjMuMjk2eiIvPgo8cGF0aCBkPSJNODUuNTkzLDUxMS4yMjdINjguNTUydi05My43MjVjMC0zOC4yNTcsMjguNTk0LTcwLjkzMiw2Ni41MjctNzYuMDExbDYxLjI3OS04LjEzN3YtMzUuMTM4aDE3LjA0MXY0Mi42MDIgIGMwLDQuMjY5LTMuMTYxLDcuODgxLTcuMzk2LDguNDQ0bC02OC42NzQsOS4xMTdjLTI5LjQ4OSwzLjk0NS01MS43MzYsMjkuMzUzLTUxLjczNiw1OS4xMTVWNTExLjIyN3oiLz4KPHBhdGggZD0iTTQ0My40NSw1MTEuMjI3aC0xNy4wNDF2LTkzLjcyNWMwLTI5Ljc2Mi0yMi4yMzgtNTUuMTc4LTUxLjc0NC01OS4xMTVsLTY4LjY2Ni05LjExN2MtNC4yMzUtMC41NjItNy4zOTYtNC4xNzUtNy4zOTYtOC40NDQgIHYtNDIuNjAyaDE3LjA0MXYzNS4xMzhsNjEuMjcsOC4xMzdjMzcuOTMzLDUuMDcsNjYuNTM2LDM3Ljc1NCw2Ni41MzYsNzYuMDExTDQ0My40NSw1MTEuMjI3TDQ0My40NSw1MTEuMjI3eiIvPgo8cmVjdCB4PSIxMzYuNzQ5IiB5PSI0NDMuMDYzIiB3aWR0aD0iMTcuMDQxIiBoZWlnaHQ9IjY4LjE2MyIvPgo8cmVjdCB4PSIzNTguMjgiIHk9IjQ0My4wNjMiIHdpZHRoPSIxNy4wNDEiIGhlaWdodD0iNjguMTYzIi8+CjxwYXRoIGQ9Ik0yMDQuODc5LDQxNy41MDJjLTEuMDM5LDAtMi4wNzktMC4xODctMy4wNzYtMC41NzFjLTIuNTgyLTAuOTk3LTQuNTE2LTMuMTk1LTUuMTg5LTUuODc5bC0xNy4wNDEtNjguMTYzbDE2LjUzLTQuMTI0ICBsMTQuMTEsNTYuNDMxbDQxLjA2LTI3LjM3Nmw5LjQ0OSwxNC4xNzhsLTUxLjEyMiwzNC4wODJDMjA4LjE4NCw0MTcuMDI1LDIwNi41MzEsNDE3LjUwMiwyMDQuODc5LDQxNy41MDJ6Ii8+CjxwYXRoIGQ9Ik0yNTYuMDAxLDM4My40MmMtMS40NTcsMC0yLjkxNC0wLjM3NS00LjIyNi0xLjEyNWwtNTkuNjQzLTM0LjA4Mmw4LjQ1Mi0xNC43OTFsNTUuNDE3LDMxLjY3bDU1LjQxNy0zMS42N2w4LjQ1MiwxNC43OTEgIGwtNTkuNjQzLDM0LjA4MkMyNTguOTE1LDM4My4wNDYsMjU3LjQ1OCwzODMuNDIsMjU2LjAwMSwzODMuNDJ6Ii8+CjxwYXRoIGQ9Ik0zMDcuMTIzLDQxNy41MDJjLTEuNjUzLDAtMy4zMDYtMC40ODYtNC43MjktMS40MzFsLTUxLjEyMi0zNC4wODJsOS40NDktMTQuMTc4bDQxLjA2LDI3LjM3NmwxNC4xMS01Ni40MzFsMTYuNTIxLDQuMTI0ICBsLTE3LjA0MSw2OC4xNjNjLTAuNjY1LDIuNjg0LTIuNjA3LDQuODgyLTUuMTg5LDUuODc5QzMwOS4yMDIsNDE3LjMxNSwzMDguMTYzLDQxNy41MDIsMzA3LjEyMyw0MTcuNTAyeiIvPgo8cGF0aCBkPSJNMjM4LjkyNiw1MTIuMDAybC0xNi45NzMtMS41NTFsOC4zNTktOTEuOTQ0bC03Ljk1OC0yMy44NzRsMTYuMTYzLTUuMzkzbDguNTIsMjUuNTYxYzAuMzY2LDEuMTE2LDAuNTExLDIuMzAxLDAuNCwzLjQ2OCAgTDIzOC45MjYsNTEyLjAwMnoiLz4KPHBhdGggZD0iTTI3My4wNjcsNTEyLjAwMmwtOC41Mi05My43MjVjLTAuMTAyLTEuMTc2LDAuMDM0LTIuMzUyLDAuNDA5LTMuNDY4bDguNTItMjUuNTYxbDE2LjE1NSw1LjM5M2wtNy45NTgsMjMuODc0bDguMzU5LDkxLjk0NCAgTDI3My4wNjcsNTEyLjAwMnoiLz4KPHJlY3QgeD0iMjM4Ljk5NCIgeT0iNDA4Ljk4MiIgd2lkdGg9IjM0LjA4MiIgaGVpZ2h0PSIxNy4wNDEiLz4KPGc+CjwvZz4KPGc+CjwvZz4KPGc+CjwvZz4KPGc+CjwvZz4KPGc+CjwvZz4KPGc+CjwvZz4KPGc+CjwvZz4KPGc+CjwvZz4KPGc+CjwvZz4KPGc+CjwvZz4KPGc+CjwvZz4KPGc+CjwvZz4KPGc+CjwvZz4KPGc+CjwvZz4KPGc+CjwvZz4KPC9zdmc+Cg==",
        }
        collection.push(item)
    }
    else {
        collection[p].latlng = L.latLng(item.position[0], item.position[1]);
        collection[p].popup = get_popup(item);
        collection[p].speed = item.speed;
        collection[p].status = item.status;
        collection[p].icon_url = item.icon;
        if(item.icon) {
            collection[p].icon = L.icon({iconUrl: item.icon, iconSize: [38, 55]});
        }
        collection[p].visible = item.status !== "CUSTOMER_IN_DEST" &&
                                item.status !== "CUSTOMER_LOCATION" &&
                                item.status !== "TRANSPORT_LOADING"; // &&
                                //item.status !== "CUSTOMER_IN_TRANSPORT" &&
    }
};

let update_station_in_collection = function (collection, item, get_popup) {
    let p = getitem(collection, item);
    if (p === false) {
        item.latlng = L.latLng(item.position[0], item.position[1]);
        item.popup = get_popup(item);
        item.visible = true;
        item.icon_url = item.icon;
        if(item.icon) {
            item.icon = L.icon({iconUrl: item.icon, iconSize: [38, 55]});
        }
        collection.push(item)
    }
    else {
        collection[p].popup = get_popup(item);
        collection[p].power = item.power;
        collection[p].places = item.places;
        collection[p].status = item.status;
        item.icon_url = item.icon;
        if(item.icon) {
            item.icon = L.icon({iconUrl: item.icon, iconSize: [38, 55]});
        }
    }
};

let getitem = function (collection, item) {
    for (let j = 0; j < collection.length; j++) {
        if (collection[j].id === item.id) {
            return j;
        }
    }
    return false;
};

let color = {
    11: "rgb(255, 170, 0)",
    13: "rgb(0, 149, 255)",
    15: "rgb(0, 255, 15)",
    41: "rgb(220, 166, 227)",
    "TRANSPORT_MOVING_TO_CUSTOMER": "rgb(255, 170, 0)",
    "TRANSPORT_MOVING_TO_DESTINATION": "rgb(0, 149, 255)",
    "TRANSPORT_MOVING_TO_STATION": "rgb(0, 255, 15)",
    "CUSTOMER_MOVING_TO_TRANSPORT": "rgb(220, 166, 227)"
};

function get_color(status) {
    return color[status];
}

let statuses = {
    10: "TRANSPORT_WAITING",
    11: "TRANSPORT_MOVING_TO_CUSTOMER",
    12: "TRANSPORT_IN_CUSTOMER_PLACE",
    13: "TRANSPORT_MOVING_TO_DESTINY",
    14: "TRANSPORT_WAITING_FOR_APPROVAL",
    15: "TRANSPORT_MOVING_TO_STATION",
    16: "TRANSPORT_IN_STATION_PLACE",
    17: "TRANSPORT_WAITING_FOR_STATION_APPROVAL",
    18: "TRANSPORT_LOADING",
    19: "TRANSPORT_LOADED",
    //
    20: "CUSTOMER_WAITING",
    21: "CUSTOMER_IN_TRANSPORT",
    22: "CUSTOMER_IN_DEST",
    23: "CUSTOMER_LOCATION",
    24: "CUSTOMER_ASSIGNED",
    //
    30: "FREE_STATION",
    31: "BUSY_STATION",
    //
    40: "CUSTOMER_WAITING_FOR_APPROVAL",
    41: "CUSTOMER_MOVING_TO_TRANSPORT",
    42: "TRANSPORT BOOKED"
};


function customer_popup(customer) {
    return "<table class='table'><tbody><tr><th>NAME</th><td>" + customer.id + "</td></tr>" +
        "<tr><th>STATUS</th><td>" + customer.status + "</td></tr>" +
        "<tr><th>POSITION</th><td>" + customer.position + "</td></tr>" +
        "<tr><th>DEST</th><td>" + customer.dest + "</td></tr>" +
        "<tr><th>TRANSPORT</th><td>" + customer.transport + "</td></tr>" +
        "<tr><th>WAITING</th><td>" + customer.waiting + "</td></tr>" +
        "</table>"
}

function transport_popup(transport) {
    return "<table class='table'><tbody><tr><th>NAME</th><td>" + transport.id + "</td></tr>" +
        "<tr><th>STATUS</th><td>" + transport.status + "</td></tr>" +
        "<tr><th>FLEETNAME</th><td>" + transport.fleet + "</td></tr>" +
        "<tr><th>TYPE</th><td>" + transport.service + "</td></tr>" +
        "<tr><th>CUSTOMER</th><td>" + transport.customer + "</td></tr>" +
        "<tr><th>POSITION</th><td>" + transport.position + "</td></tr>" +
        "<tr><th>DEST</th><td>" + transport.dest + "</td></tr>" +
        "<tr><th>ASSIGNMENTS</th><td>" + transport.assignments + "</td></tr>" +
        "<tr><th>SPEED</th><td>" + transport.speed + "</td></tr>" +
        "<tr><th>DISTANCE</th><td>" + transport.distance + "</td></tr>" +
        "<tr><th>AUTONOMY</th><td>" + transport.autonomy + " / " + transport.max_autonomy + "</td></tr>" +
        "</table>"
}

function station_popup(station) {
    return "<table class='table'><tbody><tr><th>NAME</th><td>" + station.id + "</td></tr>" +
        "<tr><th>STATUS</th><td>" + station.status + "</td></tr>" +
        "<tr><th>POSITION</th><td>" + station.position + "</td></tr>" +
        "<tr><th>POWERCHARGE</th><td>" + station.power + 'kW' + "</td></tr>" +
        "<tr><th>PLACES</th><td>" + station.places + "</td></tr>" +
        "</table>"
}
