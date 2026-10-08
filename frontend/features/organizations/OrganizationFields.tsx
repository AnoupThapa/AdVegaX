"use client";

import { useMemo, type RefObject } from "react";

import { SelectField } from "@/components/ui/SelectField";
import { TextField } from "@/components/ui/TextField";
import type { FieldErrors } from "@/features/auth/validation";

import {
  NAME_MAX_LENGTH,
  currencyOptions,
  nameErrors,
  requiredChoice,
  timeZoneOptions,
} from "./options";

export type OrganizationValues = { name: string; currency: string; timeZone: string };

export type OrganizationFieldRefs = {
  readonly name: RefObject<HTMLInputElement | null>;
  readonly currency: RefObject<HTMLSelectElement | null>;
  readonly timeZone: RefObject<HTMLSelectElement | null>;
};

/** API field names → form field names, for validation messages from the API. */
export const ORGANIZATION_FIELD_ALIASES: Readonly<Record<string, keyof OrganizationValues>> = {
  name: "name",
  default_currency: "currency",
  default_timezone: "timeZone",
};

export function validateOrganization(values: OrganizationValues): FieldErrors {
  return {
    name: nameErrors(values.name),
    currency: requiredChoice(values.currency, "Choose a currency."),
    timeZone: requiredChoice(values.timeZone, "Choose a time zone."),
  };
}

/** Focuses the first field with a problem, in form order. */
export function focusFirstError(errors: FieldErrors, refs: OrganizationFieldRefs): void {
  const order: Array<keyof OrganizationValues> = ["name", "currency", "timeZone"];
  const first = order.find((field) => errors[field]?.length);
  if (first) refs[first].current?.focus();
}

type Props = {
  readonly values: OrganizationValues;
  readonly onChange: (values: OrganizationValues) => void;
  readonly errors: FieldErrors;
  readonly refs: OrganizationFieldRefs;
  /** Saved values that must stay selectable even if this browser does not list them. */
  readonly saved?: { currency: string; timeZone: string };
};

export function OrganizationFields({ values, onChange, errors, refs, saved }: Props) {
  const { name: nameRef, currency: currencyRef, timeZone: timeZoneRef } = refs;
  const currencies = useMemo(
    () => currencyOptions(saved?.currency ?? values.currency),
    [saved?.currency, values.currency],
  );
  const zones = useMemo(
    () => timeZoneOptions(saved?.timeZone ?? values.timeZone),
    [saved?.timeZone, values.timeZone],
  );
  return (
    <>
      <TextField
        ref={nameRef}
        label="Organization name"
        name="name"
        autoComplete="organization"
        required
        maxLength={NAME_MAX_LENGTH}
        value={values.name}
        onChange={(e) => onChange({ ...values, name: e.target.value })}
        errors={errors.name ?? []}
      />
      <SelectField
        ref={currencyRef}
        label="Reporting currency"
        hint="Revenue, spend and profit are reported in this currency."
        name="currency"
        required
        placeholder="Choose a currency"
        options={currencies}
        value={values.currency}
        onChange={(e) => onChange({ ...values, currency: e.target.value })}
        errors={errors.currency ?? []}
      />
      <SelectField
        ref={timeZoneRef}
        label="Time zone"
        hint="Days and reports start at midnight in this time zone."
        name="timeZone"
        required
        placeholder="Choose a time zone"
        options={zones}
        value={values.timeZone}
        onChange={(e) => onChange({ ...values, timeZone: e.target.value })}
        errors={errors.timeZone ?? []}
      />
    </>
  );
}
