@tool
extends EditorPlugin

const EMITTER_SCRIPT := preload("res://addons/sonic_matter/runtime/sonic_foley_emitter_3d.gd")
const IMPACT_ADAPTER_SCRIPT := preload("res://addons/sonic_matter/runtime/sonic_rigid_body_impact_adapter_3d.gd")


func _enter_tree() -> void:
    add_custom_type("SonicFoleyEmitter3D", "Node3D", EMITTER_SCRIPT, null)
    add_custom_type("SonicRigidBodyImpactAdapter3D", "Node", IMPACT_ADAPTER_SCRIPT, null)


func _exit_tree() -> void:
    remove_custom_type("SonicRigidBodyImpactAdapter3D")
    remove_custom_type("SonicFoleyEmitter3D")

