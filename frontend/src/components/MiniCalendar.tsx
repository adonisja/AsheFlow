import React, { useState } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';

interface MiniCalendarProps {
  selectedDate: string;
  onSelectDate: (date: string) => void;
  getTileClassName?: (date: string) => string;
  onMonthChange?: (date: Date) => void;
}

export function MiniCalendar({ selectedDate, onSelectDate, getTileClassName, onMonthChange }: MiniCalendarProps) {
  const [currentMonth, setCurrentMonth] = useState(new Date());

  const handlePrevMonth = () => {
    const newMonth = new Date(currentMonth.getFullYear(), currentMonth.getMonth() - 1, 1);
    setCurrentMonth(newMonth);
    onMonthChange?.(newMonth);
  };

  const handleNextMonth = () => {
    const newMonth = new Date(currentMonth.getFullYear(), currentMonth.getMonth() + 1, 1);
    setCurrentMonth(newMonth);
    onMonthChange?.(newMonth);
  };

  const daysInMonth = new Date(currentMonth.getFullYear(), currentMonth.getMonth() + 1, 0).getDate();
  const firstDayOfMonth = new Date(currentMonth.getFullYear(), currentMonth.getMonth(), 1).getDay();

  const monthName = currentMonth.toLocaleString('default', { month: 'long', year: 'numeric' });
  const weekDays = ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'];

  const days = [];
  for (let i = 0; i < firstDayOfMonth; i++) {
    days.push(<div key={`empty-${i}`} className="h-8 w-8" />);
  }
  
  for (let i = 1; i <= daysInMonth; i++) {
    const d = new Date(currentMonth.getFullYear(), currentMonth.getMonth(), i);
    // Format YYYY-MM-DD local timezone
    const yyyy = d.getFullYear();
    const mm = String(d.getMonth() + 1).padStart(2, '0');
    const dd = String(d.getDate()).padStart(2, '0');
    const dateStr = `${yyyy}-${mm}-${dd}`;

    const isSelected = selectedDate === dateStr;
    const isToday = new Date().toDateString() === d.toDateString();

    let optionalClass = '';
    if (getTileClassName) {
      optionalClass = getTileClassName(dateStr) || '';
    }

    days.push(
      <button
        key={`day-${i}`}
        onClick={() => onSelectDate(dateStr)}
        className={`h-8 w-8 flex items-center justify-center rounded-full text-sm transition-colors ${
          isSelected 
            ? 'bg-primary text-primary-foreground font-semibold ring-2 ring-ring ring-offset-2 ring-offset-background' 
            : `${optionalClass || 'hover:bg-accent hover:text-accent-foreground text-foreground'}`
        } ${isToday && !isSelected ? 'border border-border' : ''}`}
      >
        {i}
      </button>
    );
  }

  return (
    <div className="bg-card border border-border rounded-xl p-4 shadow-sm w-full max-w-sm">
      <div className="flex items-center justify-between mb-4">
        <button onClick={handlePrevMonth} className="p-1 hover:bg-accent rounded-full"><ChevronLeft className="w-5 h-5 text-muted-foreground" /></button>
        <span className="font-semibold text-sm">{monthName}</span>
        <button onClick={handleNextMonth} className="p-1 hover:bg-accent rounded-full"><ChevronRight className="w-5 h-5 text-muted-foreground" /></button>
      </div>
      <div className="grid grid-cols-7 gap-1 text-center mb-2">
        {weekDays.map(day => (
          <span key={day} className="text-xs font-medium text-muted-foreground">{day}</span>
        ))}
      </div>
      <div className="grid grid-cols-7 gap-1 justify-items-center">
        {days}
      </div>
    </div>
  );
}
