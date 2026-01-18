import { useEffect, useState } from 'react';
import { Phone, Calendar, DollarSign, TrendingUp, Clock } from 'lucide-react';
import { StatCard } from './components/dashboard/StatCard';
import CallCard from './components/dashboard/CallCard';
import { api, type Call, type Stats } from './lib/api';

// Hardcode business ID for now
// Replace with your actual business UUID from backend logs
const BUSINESS_ID = 'adf0c65d-02ca-4279-a741-8e7f7bb297ad';

function App() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [calls, setCalls] = useState<Call[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 10000);
    return () => clearInterval(interval);
  }, []);

  const loadData = async () => {
    try {
      const [statsData, callsData] = await Promise.all([
        api.getStats(BUSINESS_ID),
        api.getCalls(BUSINESS_ID, 10),
      ]);
      
      setStats(statsData);
      setCalls(callsData);
      setError(null);
    } catch (err) {
      console.error('Failed to load data:', err);
      setError('Failed to load data. Make sure the backend is running on http://localhost:8000');
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-black flex items-center justify-center">
        <div className="text-white text-xl">Loading dashboard...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-black flex items-center justify-center p-6">
        <div className="glass rounded-2xl p-8 max-w-md">
          <h2 className="text-xl font-bold text-red-400 mb-2">Error Loading Data</h2>
          <p className="text-gray-300 mb-4">{error}</p>
          <button
            onClick={loadData}
            className="px-6 py-2 bg-cyan-500 hover:bg-cyan-600 rounded-xl text-white font-semibold transition-all"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-black p-6">
      {/* Background orbs */}
      <div className="fixed inset-0 overflow-hidden pointer-events-none">
        <div className="absolute top-1/4 left-1/4 w-[500px] h-[500px] bg-cyan-500/8 rounded-full blur-3xl animate-pulse-slow" />
        <div
          className="absolute bottom-1/4 right-1/4 w-[500px] h-[500px] bg-purple-500/8 rounded-full blur-3xl animate-pulse-slow"
          style={{ animationDelay: '2s' }}
        />
      </div>

      <div className="max-w-7xl mx-auto relative z-10">
        {/* Header */}
        <div className="mb-8 flex items-center justify-between">
          <div>
            <h1 className="text-4xl font-bold text-white mb-2">
              Bondi Hair Salon
            </h1>
            <p className="text-gray-400 text-sm font-medium">
              AI Receptionist Dashboard · {new Date().toLocaleDateString('en-AU', {
                weekday: 'long',
                year: 'numeric',
                month: 'long',
                day: 'numeric'
              })}
            </p>
          </div>

          <div className="flex items-center gap-3">
            <button className="px-4 py-2 glass glass-hover rounded-xl text-white/80 text-sm font-medium transition-all">
              Settings
            </button>
            <button className="px-6 py-2 bg-gradient-to-r from-cyan-500 to-cyan-600 rounded-xl text-white font-semibold hover:shadow-[0_0_30px_rgba(0,217,255,0.4)] transition-all duration-300 transform hover:-translate-y-0.5">
              Test AI Call
            </button>
          </div>
        </div>

        {/* Stats */}
        {stats && (
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
            <StatCard
              title="Total Calls Today"
              value={stats.total_calls}
              change="+23%"
              icon={Phone}
              color="cyan"
            />
            <StatCard
              title="Appointments Booked"
              value={stats.total_bookings}
              change="+18%"
              icon={Calendar}
              color="purple"
            />
            <StatCard
              title="Avg Call Duration"
              value={stats.avg_duration}
              icon={Clock}
              color="yellow"
            />
            <div className="bg-gradient-to-br from-cyan-500/15 to-purple-500/15 backdrop-blur-xl border border-cyan-500/30 rounded-2xl p-6 hover:shadow-[0_12px_40px_rgba(0,217,255,0.2)] transition-all duration-300 cursor-pointer group">
              <div className="flex items-center justify-between mb-4">
                <div className="p-3 bg-white/10 rounded-xl group-hover:bg-white/20 transition-all">
                  <TrendingUp className="w-5 h-5 text-white" />
                </div>
                <div className="px-2 py-1 bg-emerald-500/30 border border-emerald-400/50 rounded-lg text-emerald-100 text-xs font-bold">
                  Excellent
                </div>
              </div>
              <div className="text-5xl font-bold text-white mb-1">
                {stats.booking_rate}%
              </div>
              <div className="text-gray-200 text-sm font-semibold">Booking Success Rate</div>
            </div>
          </div>
        )}

        {/* Recent Calls */}
        <div className="glass rounded-2xl p-6">
          <div className="flex items-center justify-between mb-6">
            <h2 className="text-2xl font-bold text-white">Recent Calls</h2>
            <div className="flex items-center gap-2 text-sm text-gray-400 font-medium">
              <Clock className="w-4 h-4" />
              Auto-refreshing every 10s
            </div>
          </div>

          {calls.length === 0 ? (
            <div className="text-center py-12">
              <Phone className="w-16 h-16 text-gray-600 mx-auto mb-4" />
              <h3 className="text-xl font-semibold text-gray-400 mb-2">
                No calls yet
              </h3>
              <p className="text-gray-500">
                Make a test call to see it appear here in real-time!
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              {calls.map((call, index) => (
                <CallCard key={call.id} call={call} index={index} />
              ))}
            </div>
          )}

          <button className="w-full mt-4 py-3 glass glass-hover rounded-xl text-gray-300 hover:text-white transition-all duration-200 text-sm font-bold">
            View All Calls →
          </button>
        </div>

        {/* Bottom CTA */}
        <div className="mt-6 bg-gradient-to-r from-cyan-500/10 to-purple-500/10 backdrop-blur-xl border border-cyan-500/20 rounded-2xl p-6 flex items-center justify-between">
          <div>
            <h3 className="text-xl font-bold text-white mb-1">
              Your AI is performing excellently! 🎉
            </h3>
            <p className="text-gray-300 text-sm font-medium">
              {stats && `${stats.booking_rate}% booking rate · ${stats.avg_duration}s avg response · 4.8/5 customer satisfaction`}
            </p>
          </div>
          <button className="px-6 py-3 bg-gradient-to-r from-purple-500 to-purple-600 rounded-xl text-white font-bold hover:shadow-[0_0_30px_rgba(178,75,243,0.4)] transition-all duration-300 transform hover:-translate-y-0.5">
            View Analytics
          </button>
        </div>
      </div>
    </div>
  );
}

export default App;
