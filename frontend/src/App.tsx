import { useEffect, useMemo, useState } from 'react';
import { Phone, Calendar, TrendingUp, Clock } from 'lucide-react';
import { AnimatePresence, motion } from 'framer-motion';
import { StatCard } from './components/dashboard/StatCard';
import CallCard from './components/dashboard/CallCard';
import { SettingsPage } from './pages/Settings';
import { GoogleCalendarCallbackPage } from './pages/GoogleCalendarCallback';
import { api, type Call, type Stats } from './lib/api';

// Hardcode business ID for now
// Replace with your actual business UUID from backend logs
const BUSINESS_ID = 'adf0c65d-02ca-4279-a741-8e7f7bb297ad';

function App() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [calls, setCalls] = useState<Call[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeCall, setActiveCall] = useState<Call | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  
  // Check if we're on the Google Calendar callback page
  const isGoogleCalendarCallback = window.location.pathname === '/auth/google-calendar/callback';
  if (isGoogleCalendarCallback) {
    return <GoogleCalendarCallbackPage />;
  }

  useEffect(() => {
    loadData();
    checkHealth();
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
      const apiBase = import.meta.env.VITE_API_URL || 'http://localhost:8000';
      setError(`Failed to load data. Make sure the backend is running on ${apiBase}`);
    } finally {
      setLoading(false);
    }
  };

  const checkHealth = async () => {
    try {
      const health = await api.getHealth();
      console.log('API health:', health.status);
    } catch (err) {
      console.warn('API health check failed:', err);
    }
  };

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setActiveCall(null);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  useEffect(() => {
    if (!activeCall) return;
    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = originalOverflow;
    };
  }, [activeCall]);

  const transcriptLines = useMemo(() => {
    if (!activeCall?.transcript) return [];
    return activeCall.transcript.split('\n').filter(Boolean);
  }, [activeCall]);

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

  if (showSettings) {
    return <SettingsPage onBack={() => setShowSettings(false)} />;
  }

  return (
    <div className="min-h-screen bg-black p-6">
      {/* Background orbs */}
        <div className="fixed inset-0 overflow-hidden pointer-events-none">
          <div className="absolute top-1/4 left-1/4 w-[520px] h-[520px] bg-cyan-300/10 rounded-full blur-3xl animate-orb-drift" />
          <div
            className="absolute bottom-1/4 right-1/4 w-[520px] h-[520px] bg-purple-300/10 rounded-full blur-3xl animate-orb-drift-slow"
            style={{ animationDelay: '2s' }}
          />
        </div>

      <div className="max-w-7xl mx-auto relative z-10">
        {/* Header */}
        <div className="mb-8 flex items-center justify-between">
          <div>
            <h1 className="text-4xl font-display font-semibold tracking-[-0.02em] text-white mb-2">
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
            <button
              onClick={() => setShowSettings(true)}
              className="px-4 py-2 glass glass-hover rounded-xl text-white/80 text-sm font-medium transition-all"
            >
              Settings
            </button>
            <button className="px-6 py-2 bg-gradient-to-r from-cyan-400 to-cyan-600 rounded-xl text-white font-semibold hover:shadow-[0_0_30px_rgba(0,217,255,0.45)] animate-glow-breathe transition-all duration-300 transform hover:-translate-y-0.5">
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
            <div className="bg-gradient-to-br from-cyan-500/15 to-purple-500/15 backdrop-blur-xl border border-cyan-500/30 rounded-2xl p-6 hover:shadow-[0_12px_40px_rgba(0,217,255,0.2)] transition-all duration-300 cursor-pointer group card-lift">
              <div className="flex items-center justify-between mb-4">
                <div className="p-3 bg-white/10 rounded-xl group-hover:bg-white/20 transition-all">
                  <TrendingUp className="w-5 h-5 text-white" />
                </div>
                <div className="px-2 py-1 bg-emerald-500/30 border border-emerald-400/50 rounded-lg text-emerald-100 text-xs font-bold">
                  Excellent
                </div>
              </div>
              <div className="text-5xl font-display font-semibold tracking-[-0.02em] text-white mb-1">
                {stats.booking_rate}%
              </div>
              <div className="text-gray-200 text-sm font-semibold">Booking Success Rate</div>
            </div>
          </div>
        )}

        {/* Recent Calls */}
        <div className="glass rounded-2xl p-6">
          <div className="flex items-center justify-between mb-6">
            <h2 className="text-2xl font-display font-semibold tracking-tight text-white">Recent Calls</h2>
            <div className="flex items-center gap-2 text-sm text-gray-400 font-medium">
              <Clock className="w-4 h-4" />
              Auto-refreshing every 10s
            </div>
          </div>

          {calls.length === 0 ? (
            <div className="text-center py-12">
              <Phone className="w-16 h-16 text-gray-600 mx-auto mb-4" />
              <h3 className="text-xl font-display font-semibold tracking-tight text-gray-400 mb-2">
                No calls yet
              </h3>
              <p className="text-gray-500">
                Make a test call to see it appear here in real-time!
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              {calls.map((call, index) => (
                <CallCard key={call.id} call={call} index={index} onView={setActiveCall} />
              ))}
            </div>
          )}

          <button className="w-full mt-4 py-3 glass glass-hover rounded-xl text-gray-300 hover:text-white transition-all duration-200 text-sm font-bold card-lift">
            View All Calls →
          </button>
        </div>

        {/* Bottom CTA */}
        <div className="mt-6 bg-gradient-to-r from-cyan-500/10 to-purple-500/10 backdrop-blur-xl border border-cyan-500/20 rounded-2xl p-6 flex items-center justify-between card-lift">
          <div>
            <h3 className="text-xl font-display font-semibold tracking-tight text-white mb-1">
              Your AI is performing excellently! 🎉
            </h3>
            <p className="text-gray-300 text-sm font-medium">
              {stats && `${stats.booking_rate}% booking rate · ${stats.avg_duration}s avg response · 4.8/5 customer satisfaction`}
            </p>
          </div>
          <button className="px-6 py-3 bg-gradient-to-r from-purple-500 to-purple-600 rounded-xl text-white font-bold hover:shadow-[0_0_30px_rgba(178,75,243,0.45)] transition-all duration-300 transform hover:-translate-y-0.5">
            View Analytics
          </button>
        </div>
      </div>

      <AnimatePresence>
        {activeCall && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center p-6"
          >
            <div
              className="absolute inset-0 bg-black/60 backdrop-blur-sm"
              onClick={() => setActiveCall(null)}
            />
            <motion.div
              initial={{ opacity: 0, y: 20, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 20, scale: 0.98 }}
              transition={{ duration: 0.2 }}
              className="relative w-full max-w-3xl overflow-hidden rounded-3xl border border-white/10 bg-gradient-to-br from-cyan-500/10 via-white/5 to-purple-500/10 p-6 shadow-[0_45px_140px_rgba(0,0,0,0.65)]"
            >
              <div className="pointer-events-none absolute inset-0 opacity-70">
                <div className="absolute -top-24 right-0 h-56 w-56 rounded-full bg-cyan-300/15 blur-3xl" />
                <div className="absolute -bottom-24 left-10 h-56 w-56 rounded-full bg-purple-300/15 blur-3xl" />
              </div>
              <div className="relative flex items-start justify-between gap-6">
                <div>
                  <div className="text-sm text-gray-400 font-semibold uppercase tracking-[0.3em]">Call Transcript</div>
                  <div className="text-2xl font-display font-semibold tracking-tight text-white mt-2">
                    {activeCall.caller_phone}
                  </div>
                  <div className="text-gray-400 text-sm mt-1">
                    {activeCall.started_at
                      ? new Date(activeCall.started_at).toLocaleString('en-AU', {
                          weekday: 'long',
                          hour: 'numeric',
                          minute: 'numeric',
                        })
                      : 'Time unavailable'}
                  </div>
                </div>
                <button
                  onClick={() => setActiveCall(null)}
                  className="px-4 py-2 glass glass-hover rounded-xl text-white/80 text-sm font-semibold transition-all"
                >
                  Close
                </button>
                <div className="pointer-events-none absolute left-0 right-24 top-8 h-px overflow-hidden">
                  <div className="h-px w-[200%] bg-gradient-to-r from-transparent via-white/40 to-transparent animate-sheen-slide" />
                </div>
              </div>

              <div className="mt-6 relative">
                <div className="rounded-2xl border border-white/10 bg-black/30 p-5 max-h-[55vh] overflow-y-auto">
                  {transcriptLines.length > 0 ? (
                    <div className="space-y-3">
                      {transcriptLines.map((line, idx) => (
                        <div key={`${activeCall.id}-${idx}`} className="flex gap-3">
                          <div className="text-xs font-bold uppercase tracking-widest text-cyan-300 min-w-[70px]">
                            {line.startsWith('AI:') ? 'AI' : 'Customer'}
                          </div>
                          <div className="text-gray-200 text-sm leading-relaxed">
                            {line.replace(/^AI:\s?/, '').replace(/^Customer:\s?/, '')}
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="text-gray-400 text-sm">
                      Transcript not available for this call yet.
                    </div>
                  )}
                </div>
                <div className="pointer-events-none absolute inset-x-0 bottom-0 h-10 rounded-b-2xl bg-gradient-to-t from-black/50 to-transparent" />
                <div className="pointer-events-none absolute inset-x-0 bottom-2 text-center text-[11px] font-semibold uppercase tracking-[0.3em] text-white/40">
                  Scroll
                </div>
              </div>

              <div className="mt-5 flex items-center justify-between text-xs text-gray-400">
                <div>Auto-saved transcript</div>
                <div className="text-gray-500">Press Esc to close</div>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export default App;
