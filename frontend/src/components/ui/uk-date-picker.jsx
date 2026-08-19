import React, { useState } from "react";
import { format, parseISO, isValid } from "date-fns";
import { enGB } from "date-fns/locale";
import { CalendarDays } from "lucide-react";
import { Popover, PopoverTrigger, PopoverContent } from "@/components/ui/popover";
import { Calendar } from "@/components/ui/calendar";
import { cn } from "@/lib/utils";

/**
 * UK-locale date picker (dd/mm/yyyy display) backed by a yyyy-MM-dd string value,
 * so it drops straight into existing state/API calls built around native
 * <input type="date"> values.
 */
export function UkDatePicker({ value, onChange, placeholder = "dd/mm/yyyy", minDate, maxDate, className, testId, disabled }) {
  const [open, setOpen] = useState(false);
  const selected = value && isValid(parseISO(value)) ? parseISO(value) : undefined;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          disabled={disabled}
          data-testid={testId}
          className={cn(
            "inline-flex items-center gap-1.5 px-2 py-1 border border-gray-300 rounded text-xs bg-white hover:bg-gray-50 focus:outline-none focus:ring-1 focus:ring-[#1E3A8A] disabled:opacity-50 disabled:cursor-not-allowed",
            className
          )}
        >
          <CalendarDays className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" />
          <span className={selected ? "text-gray-700" : "text-gray-400"}>
            {selected ? format(selected, "dd/MM/yyyy") : placeholder}
          </span>
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-auto p-0" align="start">
        <Calendar
          mode="single"
          locale={enGB}
          weekStartsOn={1}
          selected={selected}
          defaultMonth={selected}
          disabled={(date) => (minDate && date < minDate) || (maxDate && date > maxDate)}
          onSelect={(date) => {
            onChange(date ? format(date, "yyyy-MM-dd") : "");
            setOpen(false);
          }}
        />
      </PopoverContent>
    </Popover>
  );
}
