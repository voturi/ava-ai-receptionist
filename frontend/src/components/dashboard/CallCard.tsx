import { motion } from 'framer-motion';
import { CheckCircle, XCircle, MessageSquare, User, Phone } from 'lucide-react';
import { format } from 'date-fns';
import type { Call } from '../../lib/api';

interface CallCardProps {
  call: Call;
  index: number;
  onView: (call: Call) => void;
}

const CallCard = ({ call, index, onView }: CallCardProps) => {
  const statusConfig = {
    booked: { 
      color: 'cyan', 
      icon: CheckCircle, 
      label: 'Booked', 
      dotColor: 'bg-cyan-400',
      bgColor: 'bg-cyan-400/30',
      borderColor: 'border-cyan-400/50',
      textColor: 'text-cyan-100'
    },
    inquiry: { 
      color: 'purple', 
      icon: MessageSquare, 
      label: 'Inquiry', 
      dotColor: 'bg-purple-400',
      bgColor: 'bg-purple-400/30',
      borderColor: 'border-purple-400/50',
      textColor: 'text-purple-100'
    },
    in_progress: { 
      color: 'yellow', 
      icon: Phone, 
      label: 'In Progress', 
      dotColor: 'bg-yellow-400',
      bgColor: 'bg-yellow-400/30',
      borderColor: 'border-yellow-400/50',
      textColor: 'text-yellow-100'
    },
    failed: { 
      color: 'red', 
      icon: XCircle, 
      label: 'Failed', 
      dotColor: 'bg-red-400',
      bgColor: 'bg-red-400/30',
      borderColor: 'border-red-400/50',
      textColor: 'text-red-100'
    },
  };

  const config = statusConfig[call.outcome as keyof typeof statusConfig] || statusConfig.inquiry;
  const StatusIcon = config.icon;

  const time = call.started_at ? format(new Date(call.started_at), 'h:mm a') : 'N/A';
  const duration = call.duration_seconds 
    ? `${Math.floor(call.duration_seconds / 60)}m ${call.duration_seconds % 60}s` 
    : null;

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.05 }}
      whileHover={{ scale: 1.01 }}
      className="glass glass-hover rounded-xl p-4 cursor-pointer group transition-all duration-200"
    >
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center">
        <div className={`w-2 h-2 rounded-full ${config.dotColor} shadow-[0_0_10px] ${config.dotColor}/60`} />

        <span className="text-gray-400 text-sm font-semibold min-w-[70px]">{time}</span>

        <div className="w-10 h-10 bg-gradient-to-br from-cyan-500/20 to-purple-500/20 rounded-full flex items-center justify-center border border-white/10">
          <User className="w-5 h-5 text-gray-200" />
        </div>

        <div className="flex-1">
          <div className="text-white font-semibold">{call.caller_phone}</div>
          {duration && (
            <div className="text-gray-400 text-xs font-medium">{duration}</div>
          )}
        </div>

        {call.intent && call.intent !== 'unknown' && (
          <div className="text-gray-300 text-sm font-medium capitalize">
            {call.intent}
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2 lg:justify-end">
        <div className={`flex items-center gap-1 px-2 py-1 ${config.bgColor} border ${config.borderColor} rounded-lg ${config.textColor} text-xs font-semibold`}>
          <StatusIcon className="w-3 h-3" />
          {config.label}
        </div>

        <button
          onClick={() => onView(call)}
          className="px-4 py-2 glass glass-hover rounded-lg text-gray-200 text-sm font-semibold transition-all opacity-100 lg:opacity-0 lg:group-hover:opacity-100"
        >
          View
        </button>
      </div>

      {call.transcript && (
        <div className="mt-3 pt-3 border-t border-white/5">
          <p className="text-gray-400 text-sm line-clamp-2">
            {call.transcript.split('\n')[0]}
          </p>
        </div>
      )}
    </motion.div>
  );
};

export default CallCard;
