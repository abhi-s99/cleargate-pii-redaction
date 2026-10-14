export const KNOWN_ENTITY_LABELS: Record<string, string> = {
  PERSON: 'Person Name',
  EMAIL_ADDRESS: 'Email Address',
  PHONE_NUMBER: 'Phone Number',
  EMPLOYEE_ID: 'Employee ID',
  US_SSN: 'US Social Security Number',
  IN_PAN: 'India PAN',
  PL_PESEL: 'Poland PESEL',
  PASSPORT: 'Passport Number',
  TAX_ID: 'Tax Identifier',
  DATE_OF_BIRTH: 'Date of Birth',
  HOME_ADDRESS: 'Home Address',
  FINANCIAL_PARTIAL: 'Financial Account (Partial)',
  PAYMENT_CARD: 'Payment Card',
  PHOTO: 'Facial Photograph',
  UNREADABLE_IMAGE_REGION: 'Unreadable Image Region',
};

export function getEntityLabel(type: string): string {
  return KNOWN_ENTITY_LABELS[type] || type;
}

export const ALL_KNOWN_ENTITY_TYPES = Object.keys(KNOWN_ENTITY_LABELS);
