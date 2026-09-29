import React from "react";

// Shared jurisdiction + conditional service_type dropdown logic — used by
// both the Super Admin "Create/Edit Org" modal and the public /onboard
// self-serve signup form, so the two flows can never drift on which
// jurisdiction/service_type combinations are valid.
export const JURISDICTION_OPTIONS = [
  { value: "england", label: "England (CQC / Care Certificate)" },
  { value: "wales", label: "Wales (CIW / AWIF / SCW)" },
  { value: "scotland", label: "Scotland (Care Inspectorate)" },
  { value: "northern_ireland", label: "Northern Ireland (RQIA / NISCC)" },
  { value: "ofsted", label: "Ofsted (Schools / Early Years / Children's Homes)" },
];

export const NI_SERVICE_TYPE_OPTIONS = [
  { value: "domiciliary", label: "Domiciliary Care (RQIA Dom Standards 2021)" },
  { value: "residential", label: "Residential Care (RQIA Regulations 2005)" },
];

export const OFSTED_SERVICE_TYPE_OPTIONS = [
  { value: "early_years", label: "Early Years (EYFS)" },
  { value: "childrens_home", label: "Children's Home (Quality Standards)" },
  { value: "school", label: "School (EIF)" },
];

export function JurisdictionFields({ idPrefix, jurisdiction, serviceType, onJurisdictionChange, onServiceTypeChange, inputClassName }) {
  const baseClass = inputClassName || "w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#1E3A8A]/30 focus:border-[#1E3A8A] bg-white";
  return (
    <>
      <div>
        <label htmlFor={`${idPrefix}-jurisdiction`} className="block text-sm font-medium text-gray-700 mb-1">Jurisdiction</label>
        <select
          id={`${idPrefix}-jurisdiction`}
          name="jurisdiction"
          data-testid={`${idPrefix}-jurisdiction-select`}
          value={jurisdiction}
          onChange={e => onJurisdictionChange(e.target.value)}
          className={baseClass}
        >
          {JURISDICTION_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        <p className="mt-1 text-xs text-gray-500">
          Sets which regulatory framework is used for evidence mapping and compliance reporting.
        </p>
      </div>
      {jurisdiction === "northern_ireland" && (
        <div>
          <label htmlFor={`${idPrefix}-service-type`} className="block text-sm font-medium text-gray-700 mb-1">Service Type</label>
          <select
            id={`${idPrefix}-service-type`}
            name="service_type"
            data-testid={`${idPrefix}-service-type-select`}
            value={NI_SERVICE_TYPE_OPTIONS.some(o => o.value === serviceType) ? serviceType : "domiciliary"}
            onChange={e => onServiceTypeChange(e.target.value)}
            className={baseClass}
          >
            {NI_SERVICE_TYPE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
          <p className="mt-1 text-xs text-gray-500">
            Determines whether RQIA domiciliary or residential regulations are applied. NISCC Code and Induction are shown for both.
          </p>
        </div>
      )}
      {jurisdiction === "ofsted" && (
        <div>
          <label htmlFor={`${idPrefix}-service-type`} className="block text-sm font-medium text-gray-700 mb-1">Setting Type</label>
          <select
            id={`${idPrefix}-service-type`}
            name="service_type"
            data-testid={`${idPrefix}-service-type-select`}
            value={OFSTED_SERVICE_TYPE_OPTIONS.some(o => o.value === serviceType) ? serviceType : "early_years"}
            onChange={e => onServiceTypeChange(e.target.value)}
            className={baseClass}
          >
            {OFSTED_SERVICE_TYPE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
          <p className="mt-1 text-xs text-gray-500">
            Determines which Ofsted framework is used for evidence mapping and induction tracking.
          </p>
        </div>
      )}
    </>
  );
}
