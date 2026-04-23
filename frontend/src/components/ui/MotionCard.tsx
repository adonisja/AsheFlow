import React from 'react';
import { motion, type HTMLMotionProps } from 'framer-motion';

interface Props extends HTMLMotionProps<'div'> {
  delay?: number;
  variant?: 'default' | 'glass';
  hoverable?: boolean;
}

/**
 * MotionCard — animated card wrapper with iOS-style spring entry.
 * Use `variant="glass"` for translucent frosted panels.
 */
const MotionCard = React.forwardRef<HTMLDivElement, Props>(
  ({ children, className = '', delay = 0, variant = 'default', hoverable = true, ...rest }, ref) => {
    const baseClass = variant === 'glass'
      ? 'glass rounded-2xl p-6'
      : 'card';

    const hoverProps = hoverable
      ? { whileHover: { y: -3, transition: { type: 'spring' as const, stiffness: 400, damping: 22 } } }
      : {};

    return (
      <motion.div
        ref={ref}
        initial={{ opacity: 0, y: 18 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, delay, ease: [0.22, 1, 0.36, 1] }}
        {...hoverProps}
        className={`${baseClass} ${className}`}
        {...rest}
      >
        {children}
      </motion.div>
    );
  }
);

MotionCard.displayName = 'MotionCard';

export default MotionCard;
