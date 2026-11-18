// Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

// A required provider property left blank persists as an empty string, and a
// request then goes out with that field empty. The field says so, but only
// once the user has been near it: these start blank whenever a provider is
// first selected.
import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';

import {
  ModelPropertyField,
  ModelPropertyList
} from '../../src/components/settings-panel';

const MODEL = {
  id: 'model_id',
  name: 'Model',
  description: 'Model (must support streaming)',
  value: ''
};

describe('ModelPropertyField', () => {
  it('says nothing about a blank field nobody has touched', () => {
    render(
      <ModelPropertyField
        property={MODEL}
        inputName="chat-model-id-input"
        onChange={() => undefined}
      />
    );

    const input = screen.getByRole('textbox');
    expect(input.getAttribute('aria-invalid')).toBeNull();
    expect(screen.queryByText('Model is required.')).toBeNull();
  });

  it('flags the field once the user leaves it blank', () => {
    render(
      <ModelPropertyField
        property={MODEL}
        inputName="chat-model-id-input"
        onChange={() => undefined}
      />
    );

    fireEvent.blur(screen.getByRole('textbox'));

    expect(screen.getByRole('textbox').getAttribute('aria-invalid')).toBe(
      'true'
    );
    expect(screen.getByText('Model is required.')).toBeTruthy();
  });

  it('leaves an optional property alone when it is blank', () => {
    render(
      <ModelPropertyField
        property={{
          ...MODEL,
          id: 'base_url',
          name: 'Base URL',
          optional: true
        }}
        inputName="chat-model-id-input"
        onChange={() => undefined}
      />
    );

    fireEvent.blur(screen.getByRole('textbox'));

    expect(screen.getByRole('textbox').getAttribute('aria-invalid')).toBeNull();
  });

  it('does not carry a touch onto the field that replaces it', () => {
    // The providers order their properties differently, so the list has to
    // key by identity: openai-compatible puts Model second, litellm puts Base
    // URL there. A positional key would inherit the touch and flag a field
    // the user has never been near.
    const openai = [
      { id: 'api_key', name: 'API key', description: 'API key', value: 'sk' },
      { ...MODEL, value: 'gpt-4o' }
    ];
    const litellm = [
      { ...MODEL, value: 'gpt-4o' },
      { id: 'base_url', name: 'Base URL', description: 'Base URL', value: '' }
    ];

    const { rerender } = render(
      <ModelPropertyList
        properties={openai}
        providerId="openai-compatible"
        modelId="openai-compatible-chat-model"
        inputName="chat-model-id-input"
        onPropertyChange={() => undefined}
      />
    );
    // Touch the second field, the position litellm reuses for Base URL.
    fireEvent.blur(screen.getAllByRole('textbox')[1]);

    rerender(
      <ModelPropertyList
        properties={litellm}
        providerId="litellm-compatible"
        modelId="litellm-compatible-chat-model"
        inputName="chat-model-id-input"
        onPropertyChange={() => undefined}
      />
    );

    expect(screen.queryByText('Base URL is required.')).toBeNull();
    expect(
      screen.getAllByRole('textbox')[1].getAttribute('aria-invalid')
    ).toBeNull();
  });
});

describe('ModelPropertyField secret', () => {
  it('renders a secret property as a password field', () => {
    const { container } = render(
      <ModelPropertyField
        property={{
          id: 'api_key',
          name: 'API key',
          description: 'API key',
          value: '********',
          optional: true,
          secret: true
        }}
        inputName="chat-model-id-input"
        onChange={() => undefined}
      />
    );

    const input = container.querySelector('input') as HTMLInputElement;
    expect(input.type).toBe('password');
    expect(input.autocomplete).toBe('new-password');
  });

  it('keeps a plain property as text', () => {
    const { container } = render(
      <ModelPropertyField
        property={{ ...MODEL, optional: true }}
        inputName="chat-model-id-input"
        onChange={() => undefined}
      />
    );

    expect((container.querySelector('input') as HTMLInputElement).type).toBe(
      'text'
    );
  });

  it('selects the mask on focus so typing replaces it', () => {
    const { container } = render(
      <ModelPropertyField
        property={{
          id: 'api_key',
          name: 'API key',
          description: 'API key',
          value: '********',
          optional: true,
          secret: true
        }}
        inputName="chat-model-id-input"
        onChange={() => undefined}
      />
    );
    const input = container.querySelector('input') as HTMLInputElement;
    const select = jest.spyOn(input, 'select');

    fireEvent.focus(input);

    expect(select).toHaveBeenCalledTimes(1);
  });

  it('leaves a typed key alone on focus', () => {
    const { container } = render(
      <ModelPropertyField
        property={{
          id: 'api_key',
          name: 'API key',
          description: 'API key',
          value: 'sk-typed',
          optional: true,
          secret: true
        }}
        inputName="chat-model-id-input"
        onChange={() => undefined}
      />
    );
    const input = container.querySelector('input') as HTMLInputElement;
    const select = jest.spyOn(input, 'select');

    fireEvent.focus(input);

    expect(select).not.toHaveBeenCalled();
  });
});
