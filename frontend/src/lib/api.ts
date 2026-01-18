const API_BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

export interface Call {
  id: string;
  caller_phone: string;
  started_at: string;
  duration_seconds: number | null;
  intent: string;
  outcome: string;
  transcript: string | null;
}

export interface Booking {
  id: string;
  customer_name: string;
  customer_phone: string;
  service: string;
  booking_datetime: string;
  status: string;
  created_at: string;
}

export interface Stats {
  total_calls: number;
  total_bookings: number;
  booking_rate: number;
  avg_duration: number;
}

class APIClient {
  private baseURL: string;

  constructor() {
    this.baseURL = API_BASE_URL;
  }

  async getCalls(businessId: string, limit: number = 20): Promise<Call[]> {
    const response = await fetch(
      `${this.baseURL}/api/${businessId}/calls?limit=${limit}`,
    );
    if (!response.ok) throw new Error("Failed to fetch calls");
    const data = await response.json();
    return data.calls;
  }

  async getBookings(businessId: string, limit: number = 20): Promise<Booking[]> {
    const response = await fetch(
      `${this.baseURL}/api/${businessId}/bookings?limit=${limit}`,
    );
    if (!response.ok) throw new Error("Failed to fetch bookings");
    const data = await response.json();
    return data.bookings;
  }

  async getStats(businessId: string): Promise<Stats> {
    const calls = await this.getCalls(businessId, 100);
    const bookings = await this.getBookings(businessId, 100);

    const totalCalls = calls.length;
    const totalBookings = bookings.length;
    const bookingRate = totalCalls > 0 ? (totalBookings / totalCalls) * 100 : 0;

    const durations = calls
      .filter((c) => c.duration_seconds)
      .map((c) => c.duration_seconds!);
    const avgDuration =
      durations.length > 0
        ? durations.reduce((a, b) => a + b, 0) / durations.length
        : 0;

    return {
      total_calls: totalCalls,
      total_bookings: totalBookings,
      booking_rate: Math.round(bookingRate),
      avg_duration: Math.round(avgDuration),
    };
  }
}

export const api = new APIClient();
