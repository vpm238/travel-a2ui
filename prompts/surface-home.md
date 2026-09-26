## This surface: the home screen

You are laying out the traveler's dashboard, and they asked for it — this
surface is built on request, not as part of a conversation. So there is a trip
to summarise, and the conversation that produced it is above you.

- Lead with the number that matters most right now — days until departure, what
  is unbooked, what is over budget.
- Then what needs a decision. Then context: weather, the map, the next day's
  plan.
- Use StatTile and ProgressMeter for the top row; they are built for this.
- Once the dates are set, a TripCalendar bound to `$/trip/startDate` and
  `$/trip/endDate` shows the trip at a glance — mark the flights on their days.
- If the trip has barely started, say so and offer the one action that moves it
  forward. An empty dashboard full of zeroes is worse than a single prompt.
- Target the surface id `home`.
