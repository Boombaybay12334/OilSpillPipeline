"""
models.py
=========
A) PatchClassifierCNN -- adapted from Shaban et al. 2021's 23-layer CNN,
   with 2 input channels (VV, VH) and adaptive pooling so it isn't tied to
   a fixed 64x64 input.
B) UNet -- standard 5-level U-Net, 2 input channels, configurable encoder
   channel widths.
"""

import torch
import torch.nn as nn


def _conv_bn_relu(in_ch, out_ch, kernel_size):
    padding = kernel_size // 2  # 'same' padding for odd kernel sizes
    return nn.Sequential(
        nn.Conv2d(in_ch, out_ch, kernel_size=kernel_size, padding=padding),
        nn.BatchNorm2d(out_ch),
        nn.ReLU(inplace=True),
    )


class _ConvBlock(nn.Module):
    """One conv block for PatchClassifierCNN: N conv+BN+ReLU layers with the
    given kernel size, followed by a 2x2 max pool."""

    def __init__(self, in_ch, out_ch, kernel_size, n_layers=2):
        super().__init__()
        layers = []
        for i in range(n_layers):
            layers.append(_conv_bn_relu(in_ch if i == 0 else out_ch, out_ch, kernel_size))
        self.convs = nn.Sequential(*layers)
        self.pool = nn.MaxPool2d(kernel_size=2, stride=2)

    def forward(self, x):
        x = self.convs(x)
        x = self.pool(x)
        return x


class PatchClassifierCNN(nn.Module):
    """
    23-layer-style CNN (Shaban et al. 2021), adapted for 2-channel SAR input
    and arbitrary crop size via AdaptiveAvgPool2d before the FC head.

    Conv blocks: (k=11, 32) -> (k=9, 64) -> (k=7, 128), each block =
    conv+BN+ReLU x N followed by 2x2 max pool.
    FC head: 128 -> 64 -> 32 -> 16 -> 1 (raw logit; use BCEWithLogitsLoss
    outside the model), with dropout before the final FC layers.
    """

    def __init__(self, in_channels=2, dropout=0.3, conv_layers_per_block=2):
        super().__init__()
        self.block1 = _ConvBlock(in_channels, 32, kernel_size=11, n_layers=conv_layers_per_block)
        self.block2 = _ConvBlock(32, 64, kernel_size=9, n_layers=conv_layers_per_block)
        self.block3 = _ConvBlock(64, 128, kernel_size=7, n_layers=conv_layers_per_block)

        self.global_pool = nn.AdaptiveAvgPool2d(1)

        self.dropout = nn.Dropout(dropout)
        self.fc = nn.Sequential(
            nn.Linear(128, 64),
            nn.ReLU(inplace=True),
            nn.Linear(64, 32),
            nn.ReLU(inplace=True),
            nn.Linear(32, 16),
            nn.ReLU(inplace=True),
            nn.Dropout(dropout),
            nn.Linear(16, 1),  # raw logit
        )

    def forward(self, x):
        x = self.block1(x)
        x = self.block2(x)
        x = self.block3(x)
        x = self.global_pool(x)  # (B, 128, 1, 1)
        x = torch.flatten(x, 1)  # (B, 128)
        x = self.dropout(x)
        logit = self.fc(x)  # (B, 1)
        return logit.squeeze(-1)  # (B,)


class _DoubleConv(nn.Module):
    """Two 3x3 conv + BN + ReLU layers, used at every U-Net level."""

    def __init__(self, in_ch, out_ch):
        super().__init__()
        self.block = nn.Sequential(
            _conv_bn_relu(in_ch, out_ch, kernel_size=3),
            _conv_bn_relu(out_ch, out_ch, kernel_size=3),
        )

    def forward(self, x):
        return self.block(x)


class UNet(nn.Module):
    """
    Standard 5-level U-Net.
    Encoder channel progression (default): 64 -> 128 -> 256 -> 512 -> 1024
    (bottleneck). Decoder mirrors the encoder with transposed-conv upsampling
    and skip connections. Final 1x1 conv outputs 1 raw logit channel (no
    sigmoid inside the model -- apply sigmoid only at inference/metric time).
    """

    def __init__(self, in_channels=2, out_channels=1, encoder_channels=None):
        super().__init__()
        if encoder_channels is None:
            encoder_channels = [64, 128, 256, 512, 1024]
        assert len(encoder_channels) == 5, "expected 5 encoder channel widths"
        c1, c2, c3, c4, c5 = encoder_channels

        # Encoder
        self.enc1 = _DoubleConv(in_channels, c1)
        self.enc2 = _DoubleConv(c1, c2)
        self.enc3 = _DoubleConv(c2, c3)
        self.enc4 = _DoubleConv(c3, c4)
        self.pool = nn.MaxPool2d(kernel_size=2, stride=2)

        # Bottleneck
        self.bottleneck = _DoubleConv(c4, c5)

        # Decoder
        self.up4 = nn.ConvTranspose2d(c5, c4, kernel_size=2, stride=2)
        self.dec4 = _DoubleConv(c5, c4)  # c4 (up) + c4 (skip) -> c4

        self.up3 = nn.ConvTranspose2d(c4, c3, kernel_size=2, stride=2)
        self.dec3 = _DoubleConv(c4, c3)

        self.up2 = nn.ConvTranspose2d(c3, c2, kernel_size=2, stride=2)
        self.dec2 = _DoubleConv(c3, c2)

        self.up1 = nn.ConvTranspose2d(c2, c1, kernel_size=2, stride=2)
        self.dec1 = _DoubleConv(c2, c1)

        self.final_conv = nn.Conv2d(c1, out_channels, kernel_size=1)

    def forward(self, x):
        e1 = self.enc1(x)          # c1, full res
        e2 = self.enc2(self.pool(e1))   # c2, /2
        e3 = self.enc3(self.pool(e2))   # c3, /4
        e4 = self.enc4(self.pool(e3))   # c4, /8

        b = self.bottleneck(self.pool(e4))  # c5, /16

        d4 = self.up4(b)               # c4, /8
        d4 = torch.cat([d4, e4], dim=1)
        d4 = self.dec4(d4)

        d3 = self.up3(d4)              # c3, /4
        d3 = torch.cat([d3, e3], dim=1)
        d3 = self.dec3(d3)

        d2 = self.up2(d3)              # c2, /2
        d2 = torch.cat([d2, e2], dim=1)
        d2 = self.dec2(d2)

        d1 = self.up1(d2)              # c1, full res
        d1 = torch.cat([d1, e1], dim=1)
        d1 = self.dec1(d1)

        logits = self.final_conv(d1)   # (B, out_channels, H, W)
        return logits
