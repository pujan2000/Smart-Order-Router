#!/usr/bin/env python3

import json
import sys
from pathlib import Path
from itertools import product

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt 

# Creating a Venue Class
class Venue:
    def __init__(self, publisher_id: int, ask: float, ask_size: int,
                 fee: float = 0.0, rebate: float = 0.0):
        self.publisher_id = publisher_id
        self.ask = ask
        self.ask_size = ask_size
        self.fee = fee
        self.rebate = rebate

def baseline_best_ask(df_snapshots,order_target = 5000,fee = 0.0):
    remaining = order_target
    cash_spent = 0.0
    for ts, snap in df_snapshots.groupby("ts_event", sort=True):

        snap_sorted = snap.sort_values("ask_px_00")
        for _, row in snap_sorted.iterrows():
            if remaining <= 0:
                break
            exe = min(int(row.ask_sz_00), remaining)
            cash_spent += exe * (row.ask_px_00 + fee)
            remaining -= exe
        if remaining <= 0:
            break
    return order_target - remaining, cash_spent


def baseline_twap(df_snapshots,order_target = 5_000,snapshots_per_bucket= 60,fee = 0.0):

    buckets = list(df_snapshots.groupby(np.arange(len(df_snapshots)) // snapshots_per_bucket))
    per_bucket = int(np.ceil(order_target / len(buckets)))
    remaining = order_target
    cash_spent = 0.0

    for _, bucket_df in buckets:
        if remaining <= 0:
            break
        snap = bucket_df.sort_values("ask_px_00")
        bucket_quota = min(per_bucket, remaining)
        for _, row in snap.iterrows():
            if bucket_quota <= 0:
                break
            exe = min(int(row.ask_sz_00), bucket_quota)
            cash_spent += exe * (row.ask_px_00 + fee)
            bucket_quota -= exe
            remaining -= exe
    return order_target - remaining, cash_spent


def baseline_vwap(df_snapshots,order_target= 5000,fee = 0.0):
    remaining = order_target
    cash_spent = 0.0

    for ts, snap in df_snapshots.groupby("ts_event", sort=True):
        if remaining <= 0:
            break
        total_depth = snap.ask_sz_00.sum()
        if total_depth == 0:
            continue
        for _, row in snap.iterrows():
            alloc = int(row.ask_sz_00 / total_depth * remaining)
            exe = min(alloc, int(row.ask_sz_00))
            cash_spent += exe * (row.ask_px_00 + fee)
            remaining -= exe
            if remaining <= 0:
                break
    return order_target - remaining, cash_spent

STEP = 100
# Allocate function -> copied from allocator_psuedocode.txt
def allocate(order_size, venues, lam_over, lam_under, theta_queue):
    splits = [[]]
    for v in range(len(venues)):
        new_splits = []
        for alloc in splits:
            used = sum(alloc)
            max_v = min(order_size - used, venues[v].ask_size)
            for q in range(0, max_v + STEP, STEP):
                new_splits.append(alloc + [q])
        splits = new_splits

    best_cost = np.inf
    best_split = []
    for alloc in splits:
        if sum(alloc) != order_size:
            continue
        cost = compute_cost(alloc, venues, order_size, lam_over, lam_under, theta_queue)
        if cost < best_cost:
            best_cost = cost
            best_split = alloc
    return best_split, best_cost

# Cost function -> copied from allocator_psuedocode.txt
def compute_cost(split, venues, order_size, lam_over, lam_under, theta_queue):
    executed = 0
    cash_spent = 0.0
    for i, v in enumerate(venues):
        exe = min(split[i], v.ask_size)
        executed += exe
        cash_spent += exe * (v.ask + v.fee)
        maker_rebate = max(split[i] - exe, 0) * v.rebate
        cash_spent -= maker_rebate
    underfill = max(order_size - executed, 0)
    overfill = max(executed - order_size, 0)
    risk_pen = theta_queue * (underfill + overfill)
    cost_pen = lam_under * underfill + lam_over * overfill
    return cash_spent + risk_pen + cost_pen

def execute_stream(df, param_set, order_target, venue_fees, venue_rebates):
    lam_over, lam_under, theta_q = param_set
    remaining = order_target
    cash_spent = 0.0
    executed_prices = []

    for ts, snap in df.groupby("ts_event", sort=True):
        if remaining <= 0:
            break

        venues = []
        # Assumption - Each publisher has its own fee and rebate (0 in this case) which is also constant
        for _, row in snap.iterrows():
            pid = row.publisher_id
            fee = venue_fees.get(pid, 0.0) if venue_fees else 0.0
            reb = venue_rebates.get(pid, 0.0) if venue_rebates else 0.0
            venues.append(Venue(pid, row.ask_px_00, int(row.ask_sz_00), fee, reb))

        alloc, _ = allocate(min(remaining, 5000), venues, lam_over, lam_under, theta_q)

        for qty, v in zip(alloc, venues):
            executed = min(qty, v.ask_size)
            remaining -= executed
            cash_spent += executed * (v.ask + v.fee)
            executed_prices.extend([v.ask + v.fee] * executed)

    filled = order_target - max(remaining, 0)
    return filled, cash_spent, executed_prices



def main():
    DATA_FILE = Path("l1_day.csv")
    if not DATA_FILE.exists():
        sys.stderr.write("ERROR: l1_day.csv not found\n")
        sys.exit(1)

    df = pd.read_csv(DATA_FILE, usecols=["ts_event", "publisher_id", "ask_px_00", "ask_sz_00"])
    df = df.sort_values(["ts_event", "publisher_id"]).drop_duplicates(subset=["ts_event", "publisher_id"], keep="first")
    df.reset_index(drop=True, inplace=True)

    fee_map = {}
    rebate_map = {}

    grid_lam_over  = [0.0, 0.005, 0.01, 0.02]
    grid_lam_under = [0.0, 0.005, 0.01, 0.02]
    grid_theta     = [0.0, 0.005, 0.01, 0.02]

    best_params = None
    best_cash = np.inf

    # Parameter search
    for lam_o, lam_u, theta in product(grid_lam_over, grid_lam_under, grid_theta):
        filled, cash, _ = execute_stream(df, (lam_o, lam_u, theta), 5000, fee_map, rebate_map)
        if filled < 5000:
            cash += 1e6
        if cash < best_cash:
            best_cash = cash
            best_params = (lam_o, lam_u, theta)


    # Final run
    filled_opt, cash_opt, executed_prices = execute_stream(df, best_params, 5000, fee_map, rebate_map)

    filled_ba, cash_ba = baseline_best_ask(df)
    filled_twap, cash_tw = baseline_twap(df)
    filled_vwap, cash_vw = baseline_vwap(df)

    avg_opt = cash_opt / filled_opt if filled_opt > 0 else 0
    avg_ba = cash_ba / filled_ba if filled_ba > 0 else 0
    avg_twap = cash_tw / filled_twap if filled_twap > 0 else 0
    avg_vwap = cash_vw / filled_vwap if filled_vwap > 0 else 0

    def bps(benchmark_avg, opt_avg):
        return ((benchmark_avg - opt_avg) / benchmark_avg) * 10000 if benchmark_avg != 0 else 0

    results = {
        "best_params": {
            "lambda_over": best_params[0],
            "lambda_under": best_params[1],
            "theta_queue": best_params[2],
        },
        "optimal": {
            "cash_spent": round(cash_opt, 2),
            "average_fill_price": round(avg_opt, 4),
            "filled_shares": filled_opt
        },
        "baselines": {
            "best_ask": {
                "cash_spent": round(cash_ba, 2),
                "average_fill_price": round(avg_ba, 4),
                "saving_bps": round(bps(avg_ba, avg_opt), 2)
            },
            "twap": {
                "cash_spent": round(cash_tw, 2),
                "average_fill_price": round(avg_twap, 4),
                "saving_bps": round(bps(avg_twap, avg_opt), 2)
            },
            "vwap": {
                "cash_spent": round(cash_vw, 2),
                "average_fill_price": round(avg_vwap, 4),
                "saving_bps": round(bps(avg_vwap, avg_opt), 2)
            }
        }
    }

    print(json.dumps(results, indent=2))

    try:
        if executed_prices:
            cumulative_cash = np.cumsum(executed_prices)
            plt.figure(figsize=(10, 6))
            plt.plot(cumulative_cash, color='blue')
            plt.title("Cumulative Cash Spent (Optimal Strategy)")
            plt.xlabel("Number of Shares Executed")
            plt.ylabel("Total Cash Spent ($)")
            plt.grid(True)
            plt.tight_layout()
            plt.savefig("results.png", dpi=150)
            plt.close()
        else:
            print("No shares executed - no plot generated")
    except Exception as e:
        print(f"Plotting error: {str(e)}")

if __name__ == "__main__":
    main()