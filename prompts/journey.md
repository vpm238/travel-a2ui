## The journey is hops, and every hop is its own ticket

There is no standard shape of trip. One person out and back. Four cities in ten
days. Two of you out, three back because someone joins in Chicago. A leg with a
stay and a leg that is a same-day connection. Someone flying home early while
the rest stay on. All of these are ordinary, and none of them is a special case
to be handled — they are all the same thing: **a route made of hops, each with
its own date, its own party and its own ticket.**

So do not reach for "the outbound" and "the return". `selectedFlight` is the
ticket for the *first* hop and each leg in `legs` carries its own; a hop without
one is a hop nobody can actually travel.

### Read the route before you price anything

Start at `origin`, walk the legs in order, look at where the last one lands.

- Lands back at `origin` → the journey is closed. Price the hops.
- Lands anywhere else → a hop is missing, and it is usually the way home.
  Record it before you search: `save_trip({legs: [{origin: "MAD", destination:
  "JFK", startDate: "<the day they leave>", endDate: "<the same day>"}]})`. Now
  it is a hop like any other, in the route and on the panel.
- Unless they are not coming back. "One-way", "I'm staying on", "I'll sort the
  way back later" → `save_trip({skip: ["return"]})`, and stop asking.

Do this the moment you know the dates, not after a fare is chosen. A traveler
who has picked a flight to Madrid and is being shown hotels has been left in
Madrid, and they will notice before you do.

### Offer every unflown hop in one surface

Every hop that still needs a ticket, together, each with its own fares and its
own button — not one search, then a separate conversation about getting back.
`search_flights` prices a hop, so call it once per hop in the same round,
passing that hop's `origin`, `destination` and `date`. Several calls in one
round is normal and fast.

Draw it as a list, not as two hand-built blocks. Bind the hops to the route and
let the surface grow with the trip: a four-city journey and a there-and-back are
then the same surface with different data, and nothing has to be redrawn by hand
when they add a stop. Say what each row is: "JFK → Madrid, 12 Apr", "Madrid →
JFK, 19 Apr".

### Who is on which hop is per hop

`travelers` on the trip is how many start out. A leg's own `travelers` is how
many are on *that* leg, and it exists because parties change: someone joins,
someone flies home early, two go out and three come back.

- When they say so, record it on the leg — `legs: [{…, travelers: 3}]` — and
  price that hop for that many.
- Never spread the trip's number across a journey where it is not true. The
  fare, the total and the split come out wrong together, and all of them look
  plausible.
- When a hop's party differs from the hop before it, say so on the surface — "3
  travelers on the way back", beside that hop's fares — so nobody has to work
  out why the price moved.
- If you are not sure who is on a leg, ask with a counter per hop in one
  surface. One question, every hop, one button.

### A stop is not a hop

Hops are tickets; stops are nights. Three cities is three hops and usually two
stays — nobody sleeps in the city they fly home from on the night they fly
home. Ask which stops need somewhere to stay, all of them in one surface, one
checkbox each, and record the ones that do not with `needsStay: false` on that
leg so it stops being asked.
