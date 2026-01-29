import { useState } from 'react';
import { ArrowLeft, Mail, Calendar, CheckCircle, AlertCircle } from 'lucide-react';

const BUSINESS_ID = 'adf0c65d-02ca-4279-a741-8e7f7bb297ad';
const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

interface CalendarConnection {
  name: string;
  icon: React.ReactNode;
  connected: boolean;
  email?: string;
  lastSync?: string;
  oauthStartUrl: string;
  disconnectEndpoint: string;
}

export function SettingsPage({ onBack }: { onBack: () => void }) {
  const [connections, setConnections] = useState<CalendarConnection[]>([
    {
      name: 'Google Calendar',
      icon: <Mail className="w-5 h-5" />,
      connected: false,
      oauthStartUrl: `/api/v1/auth/google-calendar/start`,
      disconnectEndpoint: `/api/v1/auth/google-calendar/disconnect`,
    },
    {
      name: 'Calendly',
      icon: <Calendar className="w-5 h-5" />,
      connected: false,
      oauthStartUrl: `/api/v1/auth/calendly/start`,
      disconnectEndpoint: `/api/v1/auth/calendly/disconnect`,
    },
  ]);

  const handleConnect = async (providerName: string) => {
    const connection = connections.find((c) => c.name === providerName);
    if (!connection) return;

    try {
      // Get the authorization URL from backend
      const response = await fetch(`${API_BASE}${connection.oauthStartUrl}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ business_id: BUSINESS_ID }),
      });

      if (response.ok) {
        const data = await response.json();
        // Redirect to Google's OAuth consent screen
        window.location.href = data.authorization_url;
      } else {
        alert('Failed to initiate OAuth flow');
      }
    } catch (error) {
      console.error('OAuth initiation error:', error);
      alert('Error connecting calendar');
    }
  };

  const handleDisconnect = async (providerName: string) => {
    const connection = connections.find((c) => c.name === providerName);
    if (!connection) return;

    try {
      const response = await fetch(`${API_BASE}${connection.disconnectEndpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ business_id: BUSINESS_ID }),
      });

      if (response.ok) {
        setConnections((prev) =>
          prev.map((c) =>
            c.name === providerName
              ? { ...c, connected: false, email: undefined, lastSync: undefined }
              : c
          )
        );
      } else {
        alert('Failed to disconnect calendar');
      }
    } catch (error) {
      console.error('Disconnect error:', error);
      alert('Error disconnecting calendar');
    }
  };

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

      <div className="max-w-4xl mx-auto relative z-10">
        {/* Header */}
        <div className="mb-8">
          <button
            onClick={onBack}
            className="flex items-center gap-2 text-gray-400 hover:text-white transition-colors mb-6"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to Dashboard
          </button>

          <div>
            <h1 className="text-4xl font-display font-semibold tracking-[-0.02em] text-white mb-2">
              Settings
            </h1>
            <p className="text-gray-400 text-sm font-medium">Manage your calendar integrations and preferences</p>
          </div>
        </div>

        {/* Calendar Integrations */}
        <div className="glass rounded-2xl p-8 mb-8">
          <h2 className="text-2xl font-display font-semibold tracking-tight text-white mb-6">
            Calendar Integrations
          </h2>

          <p className="text-gray-400 text-sm mb-8">
            Connect your calendars to automatically sync bookings and check availability in real-time.
          </p>

          <div className="space-y-4">
            {connections.map((connection) => (
              <div
                key={connection.name}
                className="border border-white/10 rounded-xl p-6 flex items-center justify-between hover:border-white/20 transition-colors"
              >
                <div className="flex items-center gap-4">
                  <div className="p-3 bg-white/5 rounded-lg text-white">{connection.icon}</div>

                  <div>
                    <h3 className="text-lg font-semibold text-white">{connection.name}</h3>
                    {connection.connected ? (
                      <div className="flex items-center gap-2 text-sm text-emerald-400 mt-1">
                        <CheckCircle className="w-4 h-4" />
                        Connected as {connection.email}
                        {connection.lastSync && (
                          <span className="text-gray-500">· Last sync {connection.lastSync}</span>
                        )}
                      </div>
                    ) : (
                      <p className="text-gray-400 text-sm mt-1">Not connected</p>
                    )}
                  </div>
                </div>

                <button
                  onClick={() =>
                    connection.connected
                      ? handleDisconnect(connection.name)
                      : handleConnect(connection.name)
                  }
                  className={`px-6 py-2 rounded-xl font-semibold transition-all ${
                    connection.connected
                      ? 'bg-red-500/20 hover:bg-red-500/30 text-red-400 border border-red-500/30'
                      : 'bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-400 border border-cyan-500/30'
                  }`}
                >
                  {connection.connected ? 'Disconnect' : 'Connect'}
                </button>
              </div>
            ))}
          </div>

          {/* Info Banner */}
          <div className="mt-6 flex gap-3 p-4 bg-blue-500/10 border border-blue-500/20 rounded-lg">
            <AlertCircle className="w-5 h-5 text-blue-400 flex-shrink-0 mt-0.5" />
            <div className="text-sm text-blue-200">
              <strong>Why connect?</strong> Automatically create events when bookings are confirmed, check
              availability in real-time, and prevent double bookings.
            </div>
          </div>
        </div>

        {/* General Settings */}
        <div className="glass rounded-2xl p-8">
          <h2 className="text-2xl font-display font-semibold tracking-tight text-white mb-6">
            General Settings
          </h2>

          <div className="space-y-6">
            {/* Timezone Setting */}
            <div className="border-b border-white/10 pb-6">
              <label className="block text-white font-semibold mb-2">Business Timezone</label>
              <select className="w-full md:w-64 px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-white focus:border-cyan-500 focus:outline-none">
                <option>Australia/Sydney</option>
                <option>Australia/Melbourne</option>
                <option>Australia/Brisbane</option>
              </select>
              <p className="text-gray-400 text-sm mt-2">Used for all booking times and calendar sync</p>
            </div>

            {/* Auto-sync Setting */}
            <div className="border-b border-white/10 pb-6">
              <div className="flex items-center justify-between">
                <div>
                  <label className="block text-white font-semibold mb-2">Auto-sync Bookings</label>
                  <p className="text-gray-400 text-sm">Automatically create calendar events for confirmed bookings</p>
                </div>
                <input type="checkbox" defaultChecked className="w-6 h-6 rounded" />
              </div>
            </div>

            {/* Save Button */}
            <div className="flex justify-end gap-3">
              <button className="px-6 py-2 glass glass-hover rounded-xl text-white font-semibold transition-all">
                Cancel
              </button>
              <button className="px-6 py-2 bg-cyan-500 hover:bg-cyan-600 rounded-xl text-white font-semibold transition-all">
                Save Changes
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
