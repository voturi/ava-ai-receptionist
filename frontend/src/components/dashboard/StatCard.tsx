import { motion } from 'framer-motion';
import type { LucideIcon } from 'lucide-react';
import { useEffect, useState } from 'react';

interface StatCardProps {
  title: string;
  value: number;
  change?: string;
  icon: LucideIcon;
  color?: 'cyan' | 'purple' | 'yellow';
}

export const StatCard = ({
  title,
  value,
  change,
  icon: Icon,
  color = 'cyan',
}: StatCardProps) => {
  const [displayValue, setDisplayValue] = useState(0);

  useEffect(() => {
    let start = 0;
    const end = value;
    const duration = 1000;
    const increment = end / (duration / 16);

    const timer = setInterval(() => {
      start += increment;
      if (start >= end) {
        setDisplayValue(end);
        clearInterval(timer);
      } else {
        setDisplayValue(Math.floor(start));
      }
    }, 16);

    return () => clearInterval(timer);
  }, [value]);

  const colorClasses = {
    cyan: 'from-cyan-500/20 to-cyan-500/5 border-cyan-500/30 group-hover:border-cyan-400/50 group-hover:shadow-[0_8px_32px_rgba(0,217,255,0.15)]',
    purple: 'from-purple-500/20 to-purple-500/5 border-purple-500/30 group-hover:border-purple-400/50 group-hover:shadow-[0_8px_32px_rgba(178,75,243,0.15)]',
    yellow: 'from-yellow-500/20 to-yellow-500/5 border-yellow-500/30 group-hover:border-yellow-400/50 group-hover:shadow-[0_8px_32px_rgba(255,184,0,0.15)]',
  };

  const iconColors = {
    cyan: 'text-cyan-300',
    purple: 'text-purple-300',
    yellow: 'text-yellow-300',
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      whileHover={{ scale: 1.02, y: -4 }}
      className={`bg-gradient-to-br ${colorClasses[color]} backdrop-blur-xl border rounded-2xl p-6 cursor-pointer group transition-all duration-300`}
    >
      <div className="flex items-center justify-between mb-4">
        <div className="p-3 bg-white/5 rounded-xl group-hover:bg-white/10 transition-all border border-white/10">
          <Icon className={`w-5 h-5 ${iconColors[color]}`} />
        </div>
        {change && (
          <div className="flex items-center gap-1 text-emerald-400 text-xs font-bold">
            <span>↑</span>
            {change}
          </div>
        )}
      </div>
      <div className="text-5xl font-display font-semibold tracking-[-0.02em] text-white mb-1">
        {displayValue}
      </div>
      <div className="text-gray-300 text-sm font-semibold">{title}</div>
    </motion.div>
  );
};
 
