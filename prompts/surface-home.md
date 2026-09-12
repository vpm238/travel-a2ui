## This surface: the home screen

You are laying out the traveler's dashboard: the first thing they see, generated
fresh for where the trip actually stands today.

- Lead with the number that matters most right now — days until departure, what
  is unbooked, what is over budget.
- Then what needs a decision. Then context: weather, the map, the next day's
  plan.
- Use StatTile and ProgressMeter for the top row; they are built for this.
- If the trip has barely started, say so and offer the one action that moves it
  forward. An empty dashboard full of zeroes is worse than a single prompt.
- Target the surface id `home`.
