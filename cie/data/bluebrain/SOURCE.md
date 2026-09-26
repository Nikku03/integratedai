# Blue Brain data used by `cie.remnet`

Files (downloaded by `python -m cie.remnet.bluebrain --fetch`; not committed):

| File | Source | sha256 |
|---|---|---|
| `pathways_physiology_factsheets_simplified.json` | https://openbluebrain.s3.amazonaws.com/Portals/nmc-portal/assets/documents/static/Download/pathways_physiology_factsheets_simplified.json | 0bf03121af020913fde54e48b6393e08984a7f3b74ecb2cfaccbc9ee211cf728 |
| `pathways_anatomy_factsheets_simplified.json` | https://openbluebrain.s3.amazonaws.com/Portals/nmc-portal/assets/documents/static/Download/pathways_anatomy_factsheets_simplified.json | c75a5fc4ce7cd4def82454352967ecf2f7789b9fd0912ac13aea2dbaae9b3bc6 |

These are the pathway factsheets of the Blue Brain Project's Neocortical Microcircuit Collaboration portal
(reconstruction of the juvenile rat somatosensory cortex microcircuit; Markram et al., Cell 163:456-492, 2015;
Ramaswamy et al., Front. Neural Circuits 2015). Physiology: per pre:post pathway, synapse type
(excitatory/inhibitory; depressing/facilitating/pseudo-linear), Tsodyks-Markram parameters U, D (ms), F (ms),
failure rate, latency, PSP amplitude. Anatomy: connection probability, synapses per connection,
convergence/divergence.

What they are used for: the parameters of short-term synaptic plasticity and release failures on the
messages of one experimental network variant. They carry no company knowledge. Check the portal's terms
before redistributing the files.
