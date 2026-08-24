#!/usr/bin/env python3
"""Render a cell-centred vorticity snapshot from foamToVTK output."""

from __future__ import annotations

import argparse

from paraview.simple import (  # type: ignore
    ColorBy,
    CreateView,
    GetColorTransferFunction,
    LegacyVTKReader,
    Render,
    SaveScreenshot,
    Show,
    _DisableFirstRenderCameraReset,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vtk", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    _DisableFirstRenderCameraReset()
    reader = LegacyVTKReader(FileNames=[args.vtk])
    view = CreateView("RenderView")
    view.ViewSize = [1400, 650]
    display = Show(reader, view)
    ColorBy(display, ("CELLS", "vorticity", "Z"))
    display.RescaleTransferFunctionToDataRange(True, False)
    lut = GetColorTransferFunction("vorticity")
    lut.ApplyPreset("Cool to Warm", True)
    lut.RescaleTransferFunction(-1.0, 1.0)
    view.CameraPosition = [2.5, 0.0, 25.0]
    view.CameraFocalPoint = [2.5, 0.0, 0.0]
    view.CameraViewUp = [0.0, 1.0, 0.0]
    view.CameraParallelScale = 2.8
    Render(view)
    SaveScreenshot(args.output, view, ImageResolution=view.ViewSize)


if __name__ == "__main__":
    main()
