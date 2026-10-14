import React from 'react';
import { getEntityLabel } from '../domain/entityLabels';

interface EntityTypeChipProps {
  entityType: string;
}

export const EntityTypeChip: React.FC<EntityTypeChipProps> = ({ entityType }) => {
  const label = getEntityLabel(entityType);

  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded bg-surface border border-border text-xs font-medium text-text"
      title={`Entity type code: ${entityType}`}
    >
      {label}
    </span>
  );
};
