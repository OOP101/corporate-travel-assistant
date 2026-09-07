import { ReactNode, useState } from 'react';
import { X as CloseIcon } from 'lucide-react';

export interface ModalFormProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  fields: Array<{
    name: string;
    label: string;
    type?: 'text' | 'number' | 'select' | 'textarea';
    options?: Array<{ value: string; label: string }>;
    placeholder?: string;
    value?: any;
    onChange?: (value: any) => void;
    rule?: { required?: boolean; message?: string };
  }>;
  onSubmit: (values: Record<string, any>) => void;
  submitText?: string;
  initialValues?: Record<string, any>;
}

export const ModalForm = ({
  isOpen,
  onClose,
  title,
  fields,
  onSubmit,
  submitText = '确定',
  initialValues = {},
}: ModalFormProps) => {
  const [values, setValues] = useState(initialValues);
  const [formErrors, setFormErrors] = useState<Record<string, string>>({});

  const handleChange = (name: string, value: any) => {
    setValues({ ...values, [name]: value });
    if (formErrors[name]) {
      setFormErrors({ ...formErrors, [name]: '' });
    }
  };

  const validate = (): boolean => {
    const errors: Record<string, string> = {};
    let isValid = true;

    fields.forEach((field) => {
      if (field.rule?.required && (!values[field.name] || values[field.name] === '' || values[field.name] === null)) {
        errors[field.name] = field.rule.message || '必填项';
        isValid = false;
      }
    });

    setFormErrors(errors);
    return isValid;
  };

  if (!isOpen) return null;

  const fieldClass = `mt-1 block w-full px-3 py-2 text-sm bg-white border border-gray-200 rounded-lg focusable resize-y`;

  return (
    <div className="fixed inset-0 bg-ink-900/40 backdrop-blur-[2px] flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-white rounded-2xl w-full max-w-lg p-6 max-h-[90vh] overflow-y-auto shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-base font-semibold text-ink-900">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-lg text-ink-400 hover:text-ink-600 hover:bg-gray-100"
          >
            <CloseIcon size={18} />
          </button>
        </div>

        {Object.keys(formErrors).length > 0 && (
          <div className="mb-4 p-3 bg-red-50 border border-red-100 rounded-lg">
            <p className="text-sm text-red-600">请修正以下错误：</p>
            <ul className="list-disc pl-4 mt-1 text-sm text-red-600 space-y-0.5">
              {Object.entries(formErrors).map(([key, msg]) => (
                <li key={key}>{msg}</li>
              ))}
            </ul>
          </div>
        )}

        <form className="space-y-4">
          {fields.map((field) => {
            const value = values[field.name] ?? initialValues[field.name] ?? '';
            return (
              <div key={field.name} className="space-y-1">
                <label className="block text-[13px] font-medium text-ink-600" htmlFor={`modal-${field.name}`}>
                  {field.label}
                </label>
                {field.type === 'select' ? (
                  <select
                    id={`modal-${field.name}`}
                    value={value}
                    onChange={(e) => handleChange(field.name, e.target.value)}
                    className={`${fieldClass} appearance-none`}
                  >
                    {field.options?.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                ) : field.type === 'textarea' ? (
                  <textarea
                    id={`modal-${field.name}`}
                    value={value}
                    onChange={(e) => handleChange(field.name, e.target.value)}
                    rows={3}
                    className={fieldClass}
                  />
                ) : field.type === 'number' ? (
                  <input
                    type="number"
                    id={`modal-${field.name}`}
                    value={value}
                    onChange={(e) => handleChange(field.name, e.target.value)}
                    className={fieldClass}
                  />
                ) : (
                  <input
                    type="text"
                    id={`modal-${field.name}`}
                    value={value}
                    onChange={(e) => handleChange(field.name, e.target.value)}
                    placeholder={field.placeholder || ''}
                    className={fieldClass}
                  />
                )}
                {formErrors[field.name] && (
                  <p className="mt-1 text-xs text-red-600">{formErrors[field.name]}</p>
                )}
              </div>
            );
          })}

          <div className="flex justify-end gap-3 mt-6">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm font-medium text-ink-600 border border-gray-200 rounded-lg hover:bg-gray-50"
            >
              取消
            </button>
            <button
              type="submit"
              onClick={() => {
                if (validate()) {
                  onSubmit(values);
                }
              }}
              className="px-4 py-2 text-sm font-medium text-white bg-primary-600 rounded-lg hover:bg-primary-700 shadow-sm shadow-primary-200"
            >
              {submitText}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
