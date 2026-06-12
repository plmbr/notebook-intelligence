// Central re-export of react-icons we use, with React-18-compatible
// types. react-icons 5.5.0+ types its icons as returning React.ReactNode,
// which @types/react@18's JSX namespace rejects as a JSX-component
// return type (TS2786). The runtime is unaffected — this module just
// re-types the icons through `FC<IIconBaseProps>` so the JSX runtime
// accepts them under React 18.
//
// Import icons from this module (e.g. `import { VscThumbsup } from '../icons'`)
// rather than directly from `react-icons/vsc`/`react-icons/md`, so a future
// bump of @types/react to v19+ only requires deleting this shim.

import type { FC, SVGAttributes } from 'react';
import type { IconType } from 'react-icons/lib';
import * as Md from 'react-icons/md';
import * as Vsc from 'react-icons/vsc';

interface IIconBaseProps extends SVGAttributes<SVGElement> {
  size?: string | number;
  color?: string;
  title?: string;
}

type IconLike = FC<IIconBaseProps>;

// Typed parameter (IconType, the upstream signature) so a typo in
// `Vsc.VscFooo` is caught at compile time. The `unknown` indirection
// is what the TS error message asks for when widening a return type
// across the React 18 → React 19 ReactNode boundary.
const asIcon = (Component: IconType): IconLike =>
  Component as unknown as IconLike;

export const VscAdd = asIcon(Vsc.VscAdd);
export const VscArrowDown = asIcon(Vsc.VscArrowDown);
export const VscArrowUp = asIcon(Vsc.VscArrowUp);
export const VscAttach = asIcon(Vsc.VscAttach);
export const VscCheck = asIcon(Vsc.VscCheck);
export const VscChevronDown = asIcon(Vsc.VscChevronDown);
export const VscChevronRight = asIcon(Vsc.VscChevronRight);
export const VscChevronUp = asIcon(Vsc.VscChevronUp);
export const VscClose = asIcon(Vsc.VscClose);
export const VscCloudUpload = asIcon(Vsc.VscCloudUpload);
export const VscCopy = asIcon(Vsc.VscCopy);
export const VscEdit = asIcon(Vsc.VscEdit);
export const VscError = asIcon(Vsc.VscError);
export const VscEye = asIcon(Vsc.VscEye);
export const VscEyeClosed = asIcon(Vsc.VscEyeClosed);
export const VscFile = asIcon(Vsc.VscFile);
export const VscHistory = asIcon(Vsc.VscHistory);
export const VscInsert = asIcon(Vsc.VscInsert);
export const VscLink = asIcon(Vsc.VscLink);
export const VscNewFile = asIcon(Vsc.VscNewFile);
export const VscNotebook = asIcon(Vsc.VscNotebook);
export const VscPassFilled = asIcon(Vsc.VscPassFilled);
export const VscRefresh = asIcon(Vsc.VscRefresh);
export const VscSend = asIcon(Vsc.VscSend);
export const VscSettingsGear = asIcon(Vsc.VscSettingsGear);
export const VscShield = asIcon(Vsc.VscShield);
export const VscSparkle = asIcon(Vsc.VscSparkle);
export const VscStopCircle = asIcon(Vsc.VscStopCircle);
export const VscSync = asIcon(Vsc.VscSync);
export const VscTerminal = asIcon(Vsc.VscTerminal);
export const VscThumbsdown = asIcon(Vsc.VscThumbsdown);
export const VscThumbsdownFilled = asIcon(Vsc.VscThumbsdownFilled);
export const VscThumbsup = asIcon(Vsc.VscThumbsup);
export const VscThumbsupFilled = asIcon(Vsc.VscThumbsupFilled);
export const VscTools = asIcon(Vsc.VscTools);
export const VscTrash = asIcon(Vsc.VscTrash);
export const VscTriangleDown = asIcon(Vsc.VscTriangleDown);
export const VscTriangleRight = asIcon(Vsc.VscTriangleRight);
export const VscWarning = asIcon(Vsc.VscWarning);

export const MdCheckBox = asIcon(Md.MdCheckBox);
export const MdOutlineCheckBoxOutlineBlank = asIcon(
  Md.MdOutlineCheckBoxOutlineBlank
);
