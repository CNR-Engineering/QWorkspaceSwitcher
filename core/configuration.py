# coding: utf-8

"""
Module de gestion de configurations en cascade.

Ce module fournit la classe :class:`Configuration`, adaptée du code CNR
pour le plugin Gestionnaire de Perspectives. Elle permet de fusionner
plusieurs sources de configuration (fichiers JSON, dictionnaires) par ordre
de priorité croissante, et d'émettre des signaux Qt lors des modifications
ou sauvegardes.

**Architecture en cascade :**

.. code-block:: text

    CONFIG_DEFAULT          (priorité la plus faible)
        ↓
    plugin_a.psp.json
        ↓
    plugin_b.psp.json
        ↓
    user.psp.json           (priorité la plus haute)
        ↓
    self.cfg                (dictionnaire fusionné en mémoire)

.. note::
    Adapté du code CNR (PBa@CNR, 2024-2026).
    Licence : BSD-2-Clause — https://opensource.org/license/BSD-2-Clause

:author: PBa@CNR (original), adapté pour GéoRelai
:license: BSD-2-Clause
"""

import os
import json
import copy

from qgis.PyQt.QtCore import QObject, pyqtSignal


class Configuration(QObject):
    """
    Gestionnaire de configuration sous forme de dictionnaire fusionné.

    Hérite de :class:`QObject` pour supporter les signaux Qt.
    Permet de charger plusieurs sources de configuration par ordre
    de priorité croissante et de les fusionner récursivement.

    **Signaux :**

    - :attr:`sgl_saved` — émis après une sauvegarde réussie.
    - :attr:`sgl_unsaved` — émis quand la configuration est modifiée
      sans avoir été sauvegardée.

    :exemple:

    .. code-block:: python

        cfg = Configuration(
            lst_cfg=[{"perspectives": []}, "user.psp.json"],
            fic_sav="user.psp.json"
        )
        cfg["perspectives"] = [{"name": "Test"}]  # émet sgl_unsaved
        cfg.save(diff=False)                       # émet sgl_saved
    """

    sgl_saved   = pyqtSignal()
    """Signal émis après une sauvegarde réussie du fichier."""

    sgl_unsaved = pyqtSignal()
    """Signal émis quand la configuration est modifiée sans sauvegarde."""

    def __init__(self, lst_cfg=None, fic_sav: str = 'user.json') -> None:
        """
        Initialise l'instance et fusionne les sources de configuration.

        Les sources sont traitées dans l'ordre de la liste — la dernière
        source est la plus dominante (priorité maximale).

        :param lst_cfg: Liste des sources de configuration. Chaque élément
            peut être un :class:`dict` ou un chemin vers un fichier JSON.
            Si ``None``, initialise avec une configuration vide.
        :type lst_cfg: list or None
        :param fic_sav: Chemin vers le fichier JSON de sauvegarde utilisateur.
        :type fic_sav: str
        """
        super().__init__()

        self.cfg          = {}
        self.cfg_statique = {}
        self.fic_sav      = os.path.normpath(fic_sav)

        if lst_cfg is None:
            lst_cfg = [{}]

        for cfg in (lst_cfg if isinstance(lst_cfg, list) else [lst_cfg]):
            self.add_cfg(cfg)

    def __setitem__(self, key, value) -> None:
        """
        Modifie ou ajoute une valeur dans la configuration via l'opérateur ``[]``.

        Émet :attr:`sgl_unsaved` si la valeur est différente de l'existante.

        :param key: Clé de configuration.
        :param value: Nouvelle valeur.

        :exemple:

        .. code-block:: python

            cfg["show_menu_bar"] = False  # émet sgl_unsaved
        """
        if self.__getitem__(key) != value:
            self.cfg[key] = value
            self.sgl_unsaved.emit()

    def __getitem__(self, key):
        """
        Retourne une valeur de configuration via l'opérateur ``[]``.

        :param key: Clé de configuration.
        :return: Valeur associée à la clé, ou ``None`` si absente.

        :exemple:

        .. code-block:: python

            perspectives = cfg["perspectives"]
        """
        return self.cfg.get(key)

    def get(self, key, dft_val=None):
        """
        Retourne une valeur de configuration avec valeur par défaut.

        :param key: Clé de configuration.
        :param dft_val: Valeur retournée si la clé est absente.
        :return: Valeur associée à la clé, ou ``dft_val`` si absente.
        :rtype: any

        :exemple:

        .. code-block:: python

            perspectives = cfg.get("perspectives", [])
        """
        return self.cfg.get(key, dft_val)

    def __contains__(self, key) -> bool:
        """
        Vérifie si une clé est présente dans la configuration via ``in``.

        :param key: Clé à vérifier.
        :return: ``True`` si la clé existe, ``False`` sinon.
        :rtype: bool

        :exemple:

        .. code-block:: python

            if "perspectives" in cfg:
                ...
        """
        return key in self.cfg

    def set_fic_sav(self, fic_sav: str) -> None:
        """
        Modifie le fichier de sauvegarde utilisateur.

        :param fic_sav: Nouveau chemin vers le fichier JSON de sauvegarde.
        :type fic_sav: str
        """
        self.fic_sav = os.path.normpath(fic_sav)

    def add_cfg(self, itm, dominante: bool = True) -> None:
        """
        Ajoute et fusionne une source de configuration.

        La source peut être un dictionnaire ou un chemin vers un fichier JSON.
        Les clés de valeur ``None`` sont ignorées.

        :param itm: Source de configuration — chemin JSON ou dictionnaire.
        :type itm: str or dict or None
        :param dominante: Si ``True``, la nouvelle source est prioritaire
            sur la configuration existante. Si ``False``, elle sert de
            complément sans écraser les valeurs existantes.
        :type dominante: bool

        :exemple:

        .. code-block:: python

            cfg.add_cfg({"show_menu_bar": True})
            cfg.add_cfg("georelai.psp.json", dominante=True)
        """
        new_cfg = None

        if itm is None:
            return

        elif isinstance(itm, str):
            itm = os.path.normpath(itm)
            try:
                with open(itm, 'r', encoding='utf-8') as f:
                    new_cfg = json.load(f) or {}
            except FileNotFoundError:
                new_cfg = {}
            except Exception as e:
                print(f"[Configuration] Erreur lecture {itm} : {e}")
                new_cfg = {}

        elif isinstance(itm, dict):
            new_cfg = itm

        if new_cfg is None:
            return

        # Supprimer les clés de valeur None
        new_cfg = {k: v for k, v in new_cfg.items() if v is not None}

        # Fusionner selon la priorité
        if dominante:
            self.cfg = self._deep_update(dic_dft=self.cfg, dic_dom=new_cfg)
        else:
            self.cfg = self._deep_update(dic_dft=new_cfg, dic_dom=self.cfg)

        # Mettre à jour la config statique (référence pour le diff)
        # Ne pas mettre à jour si c'est le fichier de sauvegarde utilisateur
        if isinstance(itm, str) and itm != self.fic_sav:
            self.cfg_statique = copy.deepcopy(self.cfg)
        elif isinstance(itm, dict):
            self.cfg_statique = copy.deepcopy(self.cfg)

    def save(self, diff: bool = True) -> None:
        """
        Sauvegarde la configuration dans :attr:`fic_sav`.

        :param diff: Si ``True``, ne sauvegarde que les différences par rapport
            à :attr:`cfg_statique` (config sans les modifications utilisateur).
            Si ``False``, sauvegarde toute la configuration.
        :type diff: bool

        :raises OSError: Si le fichier ne peut pas être écrit.

        :exemple:

        .. code-block:: python

            cfg.save(diff=True)   # sauvegarde seulement les overrides
            cfg.save(diff=False)  # sauvegarde tout
        """
        cfg_sav = self._diff(self.cfg, self.cfg_statique) if diff else self.cfg

        try:
            os.makedirs(os.path.dirname(self.fic_sav), exist_ok=True)
            with open(self.fic_sav, 'w', encoding='utf-8') as f:
                json.dump(cfg_sav, f, ensure_ascii=False, indent=2)
            self.sgl_saved.emit()
        except Exception as e:
            print(f"[Configuration] Erreur sauvegarde : {e}")

    def _deep_update(self, dic_dft: dict, dic_dom: dict) -> dict:
        """
        Fusionne récursivement deux dictionnaires.

        Les valeurs de ``dic_dom`` sont prioritaires sur celles de ``dic_dft``.
        Les sous-dictionnaires sont fusionnés récursivement.
        Les listes sont écrasées (non fusionnées).

        :param dic_dft: Dictionnaire de base (priorité faible).
        :type dic_dft: dict
        :param dic_dom: Dictionnaire dominant (priorité haute).
        :type dic_dom: dict
        :return: Nouveau dictionnaire fusionné.
        :rtype: dict

        :exemple:

        .. code-block:: python

            a = {"x": 1, "sub": {"a": 1, "b": 2}}
            b = {"x": 2, "sub": {"b": 3, "c": 4}}
            result = cfg._deep_update(a, b)
            # → {"x": 2, "sub": {"a": 1, "b": 3, "c": 4}}
        """
        if not isinstance(dic_dom, dict):
            return dic_dft
        if not isinstance(dic_dft, dict):
            return dic_dom

        d = copy.copy(dic_dft)
        for k, v in dic_dom.items():
            if isinstance(v, dict):
                d[k] = self._deep_update(d.get(k, {}), v)
            else:
                d[k] = v
        return d

    def _diff(self, itm, itm_ref) -> object:
        """
        Compare récursivement deux objets et retourne leurs différences.

        Utilisé par :meth:`save` avec ``diff=True`` pour ne sauvegarder
        que les modifications par rapport à la configuration statique.

        :param itm: Objet courant (configuration modifiée).
        :param itm_ref: Objet de référence (configuration statique).
        :return: Différences entre ``itm`` et ``itm_ref``, ou ``None``
            si les objets sont identiques.

        :exemple:

        .. code-block:: python

            base     = {"a": 1, "b": {"c": 2, "d": 3}}
            modified = {"a": 1, "b": {"c": 99, "d": 3}}
            diff = cfg._diff(modified, base)
            # → {"b": {"c": 99}}
        """
        if isinstance(itm, list) and isinstance(itm_ref, list):
            return itm

        elif isinstance(itm, dict) and isinstance(itm_ref, dict):
            diff = {}
            for k, v in itm.items():
                if k not in itm_ref:
                    diff[k] = v
                elif v != itm_ref[k]:
                    result = self._diff(v, itm_ref[k])
                    if result is not None:
                        diff[k] = result
            return diff

        elif type(itm) is not type(itm_ref):
            return itm

        elif itm != itm_ref:
            return itm

        else:
            return None