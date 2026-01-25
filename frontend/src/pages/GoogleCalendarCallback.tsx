import { useEffect, useState } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { CheckCircle, AlertCircle, Loader } from 'lucide-react';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export function GoogleCalendarCallbackPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const [status, setStatus] = useState<'loading' | 'success' | 'error'>('loading');
  const [message, setMessage] = useState('');

  useEffect(() => {
    const handleCallback = async () => {
      try {
        const code = searchParams.get('code');
        const state = searchParams.get('state');
        const error = searchParams.get('error');

        if (error) {
          setStatus('error');
          setMessage(`OAuth error: ${error}`);
          return;
        }

        if (!code || !state) {
          setStatus('error');
          setMessage('Missing authorization code or state');
          return;
        }

        // Call backend callback endpoint
        const response = await fetch(
          `${API_BASE}/api/v1/auth/google-calendar/callback?code=${code}&state=${state}`,
          {
            method: 'GET',
          }
        );

        if (response.ok) {
          setStatus('success');
          setMessage('Google Calendar connected successfully!');
          // Redirect to settings page after 2 seconds
          setTimeout(() => {
            navigate('/dashboard');
          }, 2000);
        } else {
          setStatus('error');
          const errorData = await response.json();
          setMessage(errorData.detail || 'Failed to connect Google Calendar');
        }
      } catch (error) {
        setStatus('error');
        setMessage(`Error: ${error instanceof Error ? error.message : 'Unknown error'}`);
      }
    };

    handleCallback();
  }, [searchParams, navigate]);

  return (
    <div className="min-h-screen bg-black flex items-center justify-center p-6">
      {/* Background orbs */}
      <div className="fixed inset-0 overflow-hidden pointer-events-none">
        <div className="absolute top-1/4 left-1/4 w-[520px] h-[520px] bg-cyan-300/10 rounded-full blur-3xl animate-orb-drift" />
        <div
          className="absolute bottom-1/4 right-1/4 w-[520px] h-[520px] bg-purple-300/10 rounded-full blur-3xl animate-orb-drift-slow"
          style={{ animationDelay: '2s' }}
        />
      </div>

      <div className="relative z-10 max-w-md w-full">
        <div className="glass rounded-2xl p-12 text-center">
          {status === 'loading' && (
            <>
              <Loader className="w-12 h-12 mx-auto mb-6 text-cyan-400 animate-spin" />
              <h2 className="text-2xl font-semibold text-white mb-2">Connecting Google Calendar...</h2>
              <p className="text-gray-400">Please wait while we complete the setup.</p>
            </>
          )}

          {status === 'success' && (
            <>
              <CheckCircle className="w-12 h-12 mx-auto mb-6 text-emerald-400" />
              <h2 className="text-2xl font-semibold text-white mb-2">Success!</h2>
              <p className="text-gray-400 mb-6">{message}</p>
              <p className="text-sm text-gray-500">Redirecting to dashboard...</p>
            </>
          )}

          {status === 'error' && (
            <>
              <AlertCircle className="w-12 h-12 mx-auto mb-6 text-red-400" />
              <h2 className="text-2xl font-semibold text-white mb-2">Connection Failed</h2>
              <p className="text-gray-400 mb-6">{message}</p>
              <button
                onClick={() => window.history.back()}
                className="px-6 py-2 bg-cyan-500 hover:bg-cyan-600 rounded-lg text-white font-semibold transition-all"
              >
                Go Back
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
