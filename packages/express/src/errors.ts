/**
 * Compiler errors.
 *
 * Every message is written for the model that will read it on a repair turn,
 * not for a stack trace: it names what was wrong and what was available
 * instead. That is the difference between a retry that works and one that
 * makes the same mistake with more confidence.
 */

export class ExpressError extends Error {
  override name = 'ExpressError';
}

export class ExpressSyntaxError extends ExpressError {
  override name = 'ExpressSyntaxError';
  constructor(
    message: string,
    readonly line: number,
    readonly column: number,
  ) {
    super(`Syntax error at line ${line}:${column}: ${message}`);
  }
}

export class ExpressUnknownComponentError extends ExpressError {
  override name = 'ExpressUnknownComponentError';
  constructor(component: string, available: string[]) {
    super(
      `'${component}' is not a component in this catalog. ` +
        `Available components: ${available.join(', ')}.`,
    );
  }
}

export class ExpressUnknownPropertyError extends ExpressError {
  override name = 'ExpressUnknownPropertyError';
  constructor(component: string, property: string, available: string[]) {
    super(
      `'${property}' is not a property of ${component}. ` +
        `${component} accepts: ${available.join(', ')}.`,
    );
  }
}

export class ExpressDuplicatePropertyError extends ExpressError {
  override name = 'ExpressDuplicatePropertyError';
  constructor(component: string, property: string) {
    super(
      `Property '${property}' was given twice for ${component} — once ` +
        `positionally and once by name. Pass it one way or the other.`,
    );
  }
}

export class ExpressInvalidParamError extends ExpressError {
  override name = 'ExpressInvalidParamError';
  constructor(fn: string, param: string, available: string[]) {
    super(
      `'${param}' is not a parameter of ${fn}(). ` +
        `${fn}() accepts: ${available.join(', ')}.`,
    );
  }
}

export class ExpressDuplicateParamError extends ExpressError {
  override name = 'ExpressDuplicateParamError';
  constructor(fn: string, param: string) {
    super(`Parameter '${param}' was given twice for ${fn}().`);
  }
}

export class ExpressForbiddenDatabindingError extends ExpressError {
  override name = 'ExpressForbiddenDatabindingError';
  constructor(component: string, property: string) {
    super(
      `${component}.${property} is a static property: it needs a literal value, ` +
        `not a '$' data binding.`,
    );
  }
}

export class ExpressUndefinedRootError extends ExpressError {
  override name = 'ExpressUndefinedRootError';
  constructor(variable = 'root') {
    super(
      `No '${variable}' variable was defined. Every surface needs a single ` +
        `entry point assigned to '${variable}'.`,
    );
  }
}

export class ExpressInvalidEnumError extends ExpressError {
  override name = 'ExpressInvalidEnumError';
  constructor(component: string, property: string, value: string, allowed: string[]) {
    super(
      `'${value}' is not a valid value for ${component}.${property}. ` +
        `Allowed values are: ${allowed.map((v) => `'${v}'`).join(', ')}.`,
    );
  }
}
