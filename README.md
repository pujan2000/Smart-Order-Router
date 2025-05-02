# Smart Order Router (SOR) Back-Test

## High-Level Understanding

The exercise implements a Smart Order Router (SOR) using the static allocation model from Cont & Kukanov ("Optimal Order Placement in Limit Order Markets"). The goal is to optimally distribute a 5,000-share buy order across multiple market venues to minimize execution cost while considering risk factors such as mis-execution penalties (underfill and overfill) and queue risk. The approach balances immediate market liquidity with the potential costs of executing too aggressively or conservatively.

## Detailed Process Explanation

### Data Preprocessing

* Reads provided market data (`l1_day.csv`).
* Creates Level-1 snapshots grouped by each unique timestamp (`ts_event`). Each snapshot retains only the first recorded ask price and size per venue at each timestamp, simulating real-time market visibility constraints.

### Allocation Algorithm (`allocate` function)

* Calculates all possible share allocation combinations across venues in discrete 100-share increments.
* Evaluates each combination, computing expected cost using three parameters:

  * **λ\_over**: Penalty for buying more shares than intended.
  * **λ\_under**: Penalty for buying fewer shares than intended.
  * **θ\_queue**: Queue-risk penalty associated with mis-execution (both underfill and overfill).
* Selects the combination with the lowest total cost based on these risk parameters.

### Cost Computation (`compute_cost` function)

* Computes actual cash spent based on allocated shares, prices, fees, and rebates.
* Adds penalties for overfill and underfill based on risk parameters to incentivize balanced execution.
* Ensures the optimal allocation minimizes the combination of cash spent and penalties.

### Execution Simulation (`execute_stream` function)

* Iteratively executes the allocation recommendations from the allocator at each timestamp snapshot.
* Updates remaining shares to buy after each timestamp, carrying forward any unfilled portion.
* Continues execution until the order is fully completed or the market data ends.

### Benchmarking

* Compares the optimized allocation against three baseline strategies:

  * **Best-Ask**: Always executes at the best available ask price.
  * **TWAP (Time-Weighted Average Price)**: Evenly splits the order across time intervals.
  * **VWAP (Volume-Weighted Average Price)**: Allocates shares proportionally to venue liquidity.

## Parameter Ranges

The allocator uses these risk parameters:

| Parameter | Description                     | Values Tested          |
| --------- | ------------------------------- | ---------------------- |
| λ\_over   | Penalty for extra shares bought | {0, 0.005, 0.01, 0.02} |
| λ\_under  | Penalty for unfilled shares     | {0, 0.005, 0.01, 0.02} |
| θ\_queue  | Queue-risk penalty              | {0, 0.005, 0.01, 0.02} |

These ranges were chosen to represent realistic and commonly encountered market scenarios. The lower bounds (0, 0.005) reflect a scenario with minimal execution penalties, allowing the allocator significant freedom to optimize purely for cost. Conversely, the upper bounds (0.01, 0.02) reflect more cautious scenarios where execution accuracy becomes increasingly important, representing more risk-averse trading environments.

## Results Interpretation

The optimal parameter set identified significantly reduces execution costs compared to baseline strategies. Output metrics include total cash spent, average fill price, and savings relative to each baseline in basis points.

## Recommendations for Further Improvement

### Queue-Position Slippage

To improve realism, explicitly model queue-position slippage by reducing the available liquidity at each venue based on the estimated time elapsed since the last update. This adjustment simulates the depletion of liquidity due to other traders executing ahead of your order, allowing a more realistic expectation of actual fills.

### Dynamic Step Size

Instead of using a fixed 100-share allocation increment, consider dynamically adjusting the allocation granularity. For instance, smaller increments can be used in low-liquidity scenarios to precisely match market availability, while larger increments could be applied when liquidity is abundant, thereby improving execution efficiency and computational performance.
