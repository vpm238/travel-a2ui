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

### Every hop has a party size, and it is the hop's

`travelers` on the trip is how many start out. A leg's own `travelers` is how
many are on *that* leg, and it exists because parties change: someone joins,
someone flies home early, two go out and three come back.

- **Every hop is priced for its own number.** Pass that hop's `travelers` to
  `search_flights`, not the trip's. A fare priced for the trip's number is wrong
  for the hop by exactly as many tickets as the difference, and it looks
  entirely plausible while being wrong.
- When they say so, record it on the leg: `legs: [{…, travelers: 3}]`.
- If you do not know who is on a hop, ask — a `TravelerCounter` per hop, every
  hop in one surface, one button. Not one counter for the journey.
- When a hop's party differs from the hop before it, say so on the surface — "3
  travelers on the way back", beside that hop's fares — so nobody has to work
  out why the price moved.

### Nights decide the stay and the days, hop by hop

Hops are tickets; nights are stays. Count the nights on each hop — its
`startDate` to its `endDate` — and that number decides what it needs:

- **A hop that stays the night needs somewhere to stay *and* things to do.**
  Both, every time, for every place they sleep. A city with a hotel and an empty
  itinerary is half a plan, and the traveler has to ask for the other half.
  Search the stays for that hop's nights and that hop's party, and plan the days
  it covers — `get_destination` first, so the days name real places.
- **A hop with no nights needs neither.** Landing and leaving the same day is a
  connection: no hotel, no day plan, and asking about either is the question
  that makes an agent look like a form. The hop home is usually one of these.
- **Unless they have somewhere already.** "I'm at my sister's", "the conference
  books it" → `needsStay: false` on that leg, and it stops being asked. The days
  are still worth planning: they are still there for those nights.

Three cities with four, three and two nights is three sets of stays, three day
plans and three hops — each priced for whoever is on it. Ask which stops need a
stay all in one surface, one checkbox each, rather than a city at a time.
