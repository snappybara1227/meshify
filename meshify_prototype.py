We are continuing Meshify development.

Current state:

* Detection works
* Suggestions work
* Safety works
* Ranking works
* Execution works (batch + selective)

Next step:
Implement REGION CLUSTERING.

Requirements:

* Group detected elements into clusters:

  * Ngons → group connected faces
  * Non-manifold → group connected edges

* A cluster = connected components (shared edges)

* UI:

  * Show clusters instead of individual issues
  * Example: "Ngon Cluster (5 faces)"

* Execution:

  * Apply fix ONLY to that cluster

Constraints:

* Single file
* No caching BMesh references
* Keep logic simple (DFS or BFS grouping)

Return:

1. Full script
2. What changed
3. What I should see
4. Limitations
