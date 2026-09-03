/**
 * The travel data the agent works from.
 *
 * This is a deterministic simulation, not a booking system, and it is
 * deliberately so: the point of this project is the *interface* layer — how an
 * agent describes a UI and how a host renders it — and wiring a live GDS in
 * front of that would add credentials, rate limits and flakiness to a demo
 * without teaching anything new about A2UI.
 *
 * Deterministic matters more than realistic here. The same query returns the
 * same flights on every run, so a screenshot stays true, a test can assert on a
 * price, and a user who reloads the page does not get a different trip. Swap
 * these functions for real API calls and nothing above them changes.
 */

export interface Flight {
  id: string;
  airline: string;
  flightNumber: string;
  origin: string;
  destination: string;
  departTime: string;
  arriveTime: string;
  duration: string;
  stops: string;
  price: string;
  priceValue: number;
  cabin: string;
  badge?: string;
}

export interface Hotel {
  id: string;
  name: string;
  neighborhood: string;
  rating: string;
  price: string;
  priceValue: number;
  amenities: string[];
  badge?: string;
}

export interface Destination {
  city: string;
  country: string;
  airport: string;
  currency: string;
  bestMonths: string;
  summary: string;
  highlights: Array<{ name: string; category: string; note: string }>;
}

/**
 * A small string hash used as a seed.
 *
 * FNV-1a: it is four lines, has no dependencies, and spreads short strings like
 * "MAD-2026-04-12" well enough that two adjacent dates do not produce the same
 * itinerary.
 */
function seed(input: string): number {
  let hash = 0x811c9dc5;
  for (let i = 0; i < input.length; i++) {
    hash ^= input.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return hash >>> 0;
}

function rng(state: number): () => number {
  let value = state || 1;
  return () => {
    value ^= value << 13;
    value ^= value >>> 17;
    value ^= value << 5;
    value >>>= 0;
    return value / 0xffffffff;
  };
}

const pick = <T>(items: readonly T[], random: () => number): T =>
  items[Math.floor(random() * items.length) % items.length]!;

const CITIES: Record<string, Destination> = {
  MAD: {
    city: 'Madrid',
    country: 'Spain',
    airport: 'MAD',
    currency: 'EUR',
    bestMonths: 'April–June, September–October',
    summary:
      'Dense, walkable and late-running. The art is world class and the eating starts at 21:00.',
    highlights: [
      { name: 'Museo del Prado', category: 'sight', note: 'Go at opening or in the last free hours' },
      { name: 'Mercado de San Fernando', category: 'food', note: 'Cheaper and less touristed than San Miguel' },
      { name: 'Retiro Park', category: 'outdoors', note: 'Rowboats on the lake until 19:00' },
      { name: 'Toledo day trip', category: 'sight', note: '33 minutes by AVE from Atocha' },
    ],
  },
  LIS: {
    city: 'Lisbon',
    country: 'Portugal',
    airport: 'LIS',
    currency: 'EUR',
    bestMonths: 'March–June, September–October',
    summary: 'Hills, tiles and light. Plan for the gradients — the trams exist for a reason.',
    highlights: [
      { name: 'Alfama at dawn', category: 'sight', note: 'Empty streets before the tour groups' },
      { name: 'Time Out Market', category: 'food', note: 'Busy at 13:00; go at 11:30' },
      { name: 'Sintra', category: 'sight', note: 'A full day, and book Pena Palace ahead' },
      { name: 'Belém', category: 'food', note: 'The pastéis really are better at the original' },
    ],
  },
  CDG: {
    city: 'Paris',
    country: 'France',
    airport: 'CDG',
    currency: 'EUR',
    bestMonths: 'April–June, September–October',
    summary: 'Everything you expect, plus a lot that only shows up if you walk between the sights.',
    highlights: [
      { name: 'Musée d’Orsay', category: 'sight', note: 'Better than the Louvre for a first visit' },
      { name: 'Canal Saint-Martin', category: 'outdoors', note: 'Sunday, when the roads close' },
      { name: 'Marché d’Aligre', category: 'food', note: 'Morning market, closed Mondays' },
    ],
  },
  NRT: {
    city: 'Tokyo',
    country: 'Japan',
    airport: 'NRT',
    currency: 'JPY',
    bestMonths: 'March–May, October–November',
    summary: 'Vast and legible at once. Pick two neighbourhoods a day and do them properly.',
    highlights: [
      { name: 'Tsukiji outer market', category: 'food', note: 'Before 09:00 or not at all' },
      { name: 'Shimokitazawa', category: 'shopping', note: 'Second-hand, coffee, small venues' },
      { name: 'Meiji Jingu', category: 'outdoors', note: 'Enter from Harajuku, leave via Yoyogi' },
    ],
  },
  MEX: {
    city: 'Mexico City',
    country: 'Mexico',
    airport: 'MEX',
    currency: 'MXN',
    bestMonths: 'March–May, October–November',
    summary: 'A capital that rewards a slow itinerary. Altitude is real on the first day.',
    highlights: [
      { name: 'Museo Nacional de Antropología', category: 'sight', note: 'Half a day, minimum' },
      { name: 'Mercado de Coyoacán', category: 'food', note: 'Tostadas, then the Frida Kahlo house' },
      { name: 'Roma Norte', category: 'food', note: 'Where to eat every evening' },
    ],
  },
  ATH: {
    city: 'Athens',
    country: 'Greece',
    airport: 'ATH',
    currency: 'EUR',
    bestMonths: 'April–June, September–October',
    summary: 'Ancient and scruffy and excellent. The islands are two hours away when you want them.',
    highlights: [
      { name: 'Acropolis', category: 'sight', note: 'First entry slot, before the heat' },
      { name: 'Anafiotika', category: 'sight', note: 'Island village inside the city' },
      { name: 'Varvakios market', category: 'food', note: 'Not for the squeamish; superb' },
    ],
  },
};

const CITY_ALIASES: Record<string, string> = {
  madrid: 'MAD',
  spain: 'MAD',
  lisbon: 'LIS',
  lisboa: 'LIS',
  portugal: 'LIS',
  paris: 'CDG',
  france: 'CDG',
  tokyo: 'NRT',
  japan: 'NRT',
  'mexico city': 'MEX',
  cdmx: 'MEX',
  mexico: 'MEX',
  athens: 'ATH',
  greece: 'ATH',
};

const AIRLINES = [
  { name: 'Iberia', code: 'IB' },
  { name: 'Delta', code: 'DL' },
  { name: 'TAP Air Portugal', code: 'TP' },
  { name: 'Air France', code: 'AF' },
  { name: 'United', code: 'UA' },
  { name: 'Lufthansa', code: 'LH' },
  { name: 'American', code: 'AA' },
] as const;

const NEIGHBOURHOODS: Record<string, string[]> = {
  MAD: ['Malasaña', 'La Latina', 'Chueca', 'Salamanca', 'Lavapiés'],
  LIS: ['Alfama', 'Príncipe Real', 'Baixa', 'Graça', 'Cais do Sodré'],
  CDG: ['Le Marais', 'Canal Saint-Martin', 'Saint-Germain', 'Belleville'],
  NRT: ['Shibuya', 'Yanaka', 'Nakameguro', 'Kagurazaka'],
  MEX: ['Roma Norte', 'Condesa', 'Juárez', 'Coyoacán'],
  ATH: ['Koukaki', 'Plaka', 'Exarchia', 'Kolonaki'],
};

const HOTEL_WORDS = ['Casa', 'Hotel', 'Residencia', 'The', 'Pensão', 'Villa'];
const HOTEL_NAMES = ['Aurora', 'Verano', 'Miradouro', 'Barrio', 'Lumière', 'Alta', 'Nueve', 'Bruma'];
const AMENITIES = ['Breakfast', 'Rooftop', 'Air-con', 'Kitchenette', 'Late check-out', 'Bikes', 'Laundry'];

const CURRENCY_SYMBOL: Record<string, string> = { EUR: '€', USD: '$', JPY: '¥', MXN: 'MX$', GBP: '£' };

/**
 * Departure airports, and the IANA timezones they serve.
 *
 * Used to turn a browser's timezone into a *suggestion* — never a default. The
 * app used to price every trip out of JFK regardless of who was asking, which
 * is wrong in the same way inventing a date is wrong: it produces a real-looking
 * number for a journey nobody described.
 */
export interface OriginAirport {
  code: string;
  city: string;
  zones: string[];
}

const ORIGINS: OriginAirport[] = [
  { code: 'JFK', city: 'New York', zones: ['America/New_York', 'America/Detroit', 'America/Toronto'] },
  { code: 'ORD', city: 'Chicago', zones: ['America/Chicago', 'America/Winnipeg'] },
  { code: 'DEN', city: 'Denver', zones: ['America/Denver', 'America/Edmonton', 'America/Phoenix'] },
  { code: 'LAX', city: 'Los Angeles', zones: ['America/Los_Angeles', 'America/Vancouver', 'America/Tijuana'] },
  { code: 'MIA', city: 'Miami', zones: ['America/Bogota', 'America/Lima', 'America/Panama'] },
  { code: 'GRU', city: 'São Paulo', zones: ['America/Sao_Paulo', 'America/Argentina/Buenos_Aires'] },
  { code: 'LHR', city: 'London', zones: ['Europe/London', 'Europe/Dublin', 'Europe/Lisbon'] },
  { code: 'CDG', city: 'Paris', zones: ['Europe/Paris', 'Europe/Brussels', 'Europe/Madrid', 'Europe/Amsterdam'] },
  { code: 'FRA', city: 'Frankfurt', zones: ['Europe/Berlin', 'Europe/Zurich', 'Europe/Vienna', 'Europe/Prague', 'Europe/Rome'] },
  { code: 'DXB', city: 'Dubai', zones: ['Asia/Dubai', 'Asia/Riyadh', 'Asia/Qatar'] },
  { code: 'DEL', city: 'Delhi', zones: ['Asia/Kolkata', 'Asia/Calcutta', 'Asia/Karachi', 'Asia/Kathmandu'] },
  { code: 'SIN', city: 'Singapore', zones: ['Asia/Singapore', 'Asia/Kuala_Lumpur', 'Asia/Jakarta', 'Asia/Bangkok'] },
  { code: 'HKG', city: 'Hong Kong', zones: ['Asia/Hong_Kong', 'Asia/Shanghai', 'Asia/Taipei', 'Asia/Manila'] },
  { code: 'NRT', city: 'Tokyo', zones: ['Asia/Tokyo', 'Asia/Seoul'] },
  { code: 'SYD', city: 'Sydney', zones: ['Australia/Sydney', 'Australia/Melbourne', 'Australia/Brisbane'] },
  { code: 'JNB', city: 'Johannesburg', zones: ['Africa/Johannesburg', 'Africa/Nairobi', 'Africa/Lagos'] },
];

export function knownOrigins(): OriginAirport[] {
  return ORIGINS;
}

/**
 * The airport a timezone suggests, or nothing.
 *
 * Returning nothing is a perfectly good answer — better than reaching for the
 * nearest continent. The caller offers what it gets as a pre-filled choice the
 * traveler confirms, and asks outright when there is nothing to offer.
 */
export function originForTimeZone(timeZone: string | undefined): OriginAirport | undefined {
  if (!timeZone) return undefined;
  const exact = ORIGINS.find((entry) => entry.zones.includes(timeZone));
  if (exact) return exact;
  // Fall back to the region only: 'Europe/Warsaw' is not listed, but a European
  // hub is a far better prompt than New York.
  const region = timeZone.split('/')[0];
  return ORIGINS.find((entry) => entry.zones.some((zone) => zone.split('/')[0] === region));
}

/** Resolves whatever the model typed into an airport code we know about. */
export function resolveDestination(query: string): Destination | undefined {
  const trimmed = (query ?? '').trim();
  if (!trimmed) return undefined;
  const upper = trimmed.toUpperCase();
  if (CITIES[upper]) return CITIES[upper];
  const alias = CITY_ALIASES[trimmed.toLowerCase()];
  if (alias) return CITIES[alias];
  // Last resort: a substring match, so "a few days in Madrid" still resolves.
  const lowered = trimmed.toLowerCase();
  for (const [name, code] of Object.entries(CITY_ALIASES)) {
    if (lowered.includes(name)) return CITIES[code];
  }
  return undefined;
}

export function knownDestinations(): Destination[] {
  return Object.values(CITIES);
}

function money(amount: number, currency: string): string {
  const symbol = CURRENCY_SYMBOL[currency] ?? `${currency} `;
  return `${symbol}${Math.round(amount).toLocaleString('en-US')}`;
}

function clockTime(minutes: number): string {
  const wrapped = ((minutes % 1440) + 1440) % 1440;
  const hours = Math.floor(wrapped / 60);
  const mins = wrapped % 60;
  const nextDay = minutes >= 1440 ? ' +1' : '';
  return `${String(hours).padStart(2, '0')}:${String(mins).padStart(2, '0')}${nextDay}`;
}

export interface FlightQuery {
  origin?: string;
  destination: string;
  date?: string;
  travelers?: number;
  cabin?: string;
  maxPrice?: number;
  nonstopOnly?: boolean;
}

export function searchFlights(query: FlightQuery): { flights: Flight[]; currency: string; note: string } {
  const destination = resolveDestination(query.destination);
  const destinationCode = destination?.airport ?? query.destination.slice(0, 3).toUpperCase();
  const origin = (query.origin ?? 'JFK').slice(0, 3).toUpperCase();
  const date = query.date ?? '';
  const cabin = query.cabin ?? 'economy';

  const random = rng(seed(`${origin}-${destinationCode}-${date}-${cabin}`));
  const cabinMultiplier = { economy: 1, premium: 1.7, business: 3.4, first: 5.6 }[cabin] ?? 1;
  const base = 280 + random() * 260;

  const flights: Flight[] = [];
  const used = new Set<string>();

  for (let index = 0; index < 5; index++) {
    let airline = pick(AIRLINES, random);
    let guard = 0;
    while (used.has(airline.code) && guard++ < 8) airline = pick(AIRLINES, random);
    used.add(airline.code);

    const stops = index === 4 || random() < 0.28;
    const departMinutes = Math.floor(6 * 60 + random() * 15 * 60);
    const legMinutes = Math.floor((stops ? 620 : 430) + random() * 140);
    const price = base * cabinMultiplier * (stops ? 0.82 : 1) * (0.9 + random() * 0.4);

    flights.push({
      id: `${airline.code}${1000 + Math.floor(random() * 8000)}`,
      airline: airline.name,
      flightNumber: `${airline.code}${100 + Math.floor(random() * 899)}`,
      origin,
      destination: destinationCode,
      departTime: clockTime(departMinutes),
      arriveTime: clockTime(departMinutes + legMinutes),
      duration: `${Math.floor(legMinutes / 60)}h ${legMinutes % 60}m`,
      stops: stops ? `1 stop · ${pick(['LIS', 'LHR', 'CDG', 'AMS', 'FRA'], random)}` : 'Nonstop',
      price: money(price, 'USD'),
      priceValue: Math.round(price),
      cabin,
    });
  }

  let results = flights;
  if (query.nonstopOnly) results = results.filter((flight) => flight.stops === 'Nonstop');
  if (query.maxPrice) results = results.filter((flight) => flight.priceValue <= query.maxPrice!);
  results.sort((a, b) => a.priceValue - b.priceValue);

  if (results.length > 0) {
    results[0]!.badge = 'Cheapest';
    const fastest = [...results].sort(
      (a, b) => durationMinutes(a.duration) - durationMinutes(b.duration),
    )[0]!;
    if (fastest.id !== results[0]!.id) fastest.badge = 'Fastest';
  }

  const shown = results.slice(0, 4);
  const note = shown.length
    ? `${shown.length} option(s) for ${origin} → ${destinationCode}${date ? ` on ${date}` : ''}.`
    : 'No options matched. Try relaxing the price cap or allowing a stop.';

  return { flights: shown, currency: 'USD', note };
}

function durationMinutes(duration: string): number {
  const match = /(\d+)h\s*(\d+)?/.exec(duration);
  return match ? Number(match[1]) * 60 + Number(match[2] ?? 0) : 0;
}

export interface HotelQuery {
  destination: string;
  nights?: number;
  travelers?: number;
  maxNightly?: number;
  neighborhood?: string;
}

export function searchHotels(query: HotelQuery): { hotels: Hotel[]; currency: string; note: string } {
  const destination = resolveDestination(query.destination);
  const code = destination?.airport ?? 'MAD';
  const currency = destination?.currency ?? 'EUR';
  const nights = query.nights ?? 5;
  const random = rng(seed(`hotels-${code}-${nights}-${query.neighborhood ?? ''}`));
  const areas = NEIGHBOURHOODS[code] ?? ['Centre'];

  const hotels: Hotel[] = [];
  for (let index = 0; index < 5; index++) {
    const nightly = 95 + random() * 240;
    const amenityCount = 2 + Math.floor(random() * 3);
    const amenities: string[] = [];
    while (amenities.length < amenityCount) {
      const amenity = pick(AMENITIES, random);
      if (!amenities.includes(amenity)) amenities.push(amenity);
    }
    hotels.push({
      id: `h_${code}_${index}`,
      name: `${pick(HOTEL_WORDS, random)} ${pick(HOTEL_NAMES, random)}`,
      neighborhood: query.neighborhood || pick(areas, random),
      rating: `${(3.9 + random() * 1.05).toFixed(1)} (${200 + Math.floor(random() * 1800)})`,
      price: `${money(nightly, currency)} / night`,
      priceValue: Math.round(nightly),
      amenities,
    });
  }

  let results = hotels;
  if (query.maxNightly) results = results.filter((hotel) => hotel.priceValue <= query.maxNightly!);
  results.sort((a, b) => a.priceValue - b.priceValue);
  if (results.length > 0) {
    results[0]!.badge = 'Best value';
    if (results.length > 2) results[results.length - 1]!.badge = 'Most central';
  }

  const shown = results.slice(0, 4);
  return {
    hotels: shown,
    currency,
    note: shown.length
      ? `${shown.length} stay(s) in ${destination?.city ?? code} for ${nights} night(s).`
      : 'No stays under that nightly cap. Raise it or widen the area.',
  };
}

const CONDITIONS = ['sun', 'sun', 'cloud', 'cloud', 'rain', 'fog'] as const;
const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'] as const;

export function getWeather(
  destinationQuery: string,
  startDate?: string,
  days = 5,
): { place: string; days: Array<{ day: string; high: string; low: string; condition: string }>; note: string } {
  const destination = resolveDestination(destinationQuery);
  const place = destination?.city ?? destinationQuery;
  const start = startDate ? new Date(startDate) : new Date();
  const random = rng(seed(`weather-${place}-${startDate ?? ''}`));

  const forecast = [];
  let high = 14 + random() * 12;
  for (let index = 0; index < Math.min(Math.max(days, 1), 7); index++) {
    high += random() * 6 - 3;
    const low = high - (5 + random() * 4);
    const date = new Date(start.getTime() + index * 86_400_000);
    forecast.push({
      day: WEEKDAYS[date.getUTCDay()] ?? 'Day',
      high: `${Math.round(high)}°`,
      low: `${Math.round(low)}°`,
      condition: pick(CONDITIONS, random),
    });
  }

  const wet = forecast.filter((entry) => entry.condition === 'rain').length;
  const note = wet > 1 ? 'Rain on more than one day — pack a shell.' : 'Mostly dry; a light jacket is enough.';
  return { place, days: forecast, note };
}

export interface PriceEstimate {
  lines: Array<{ label: string; amount: string; note?: string }>;
  total: string;
  totalValue: number;
  currency: string;
}

export function estimateTrip(input: {
  destination: string;
  travelers?: number;
  nights?: number;
  flightPrice?: number;
  nightlyPrice?: number;
}): PriceEstimate {
  const destination = resolveDestination(input.destination);
  const currency = 'USD';
  const travelers = Math.max(1, input.travelers ?? 2);
  const nights = Math.max(1, input.nights ?? 5);
  const random = rng(seed(`estimate-${destination?.airport ?? input.destination}-${travelers}-${nights}`));

  const flight = (input.flightPrice ?? 380 + random() * 180) * travelers;
  const stay = (input.nightlyPrice ?? 140 + random() * 90) * nights;
  const food = 55 * travelers * (nights + 1);
  const local = 24 * (nights + 1);

  const lines = [
    { label: `Flights (${travelers} traveler${travelers > 1 ? 's' : ''})`, amount: money(flight, currency) },
    { label: `Stay (${nights} night${nights > 1 ? 's' : ''})`, amount: money(stay, currency) },
    { label: 'Food and drink', amount: money(food, currency), note: 'estimated' },
    { label: 'Local transport', amount: money(local, currency), note: 'metro and taxis' },
  ];

  const total = flight + stay + food + local;
  return { lines, total: money(total, currency), totalValue: Math.round(total), currency };
}
